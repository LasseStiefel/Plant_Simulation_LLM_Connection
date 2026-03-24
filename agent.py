import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from agents import Agent, Runner
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from model_handling import PARAMETERS_PATH, RESULTS_PATH, _open_model

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
print(api_key is not None)


BASE_DIR = Path(__file__).resolve().parent
PARAMETER_MAPPING_FILE = BASE_DIR / "parameter_mapping.json"
SIMULATION_TIMEOUT_SECONDS = 300
RUN_SIMULATION_COMMANDS = (
    "run simulation",
    "start simulation",
    "run the simulation",
    "start the simulation",
    "run model",
    "start model",
    "run the model",
    "start the model",
    "execute simulation",
    "execute the simulation",
)
RUN_SIMULATION_PREFIXES = ("", "please ")
RUN_SIMULATION_JOINERS = (" and ", " then ", "; ")
RUN_SIMULATION_NEGATIONS = (
    "don't run",
    "do not run",
    "dont run",
    "not run",
    "not yet",
    "wait",
    "hold off",
    "without running",
)
EXIT_COMMANDS = {"exit", "quit", "bye"}

JsonScalar = int | float | str | bool | None


class ParameterDefinition(BaseModel):
    description: str
    route: str
    format: str
    value: JsonScalar


class ParameterValueUpdate(BaseModel):
    name: str = Field(description="Exact parameter name from the mapping JSON")
    value: JsonScalar = Field(description="New value for that parameter")


class ParameterUpdateResponse(BaseModel):
    updates: list[ParameterValueUpdate] = Field(
        default_factory=list,
        description="Only include parameters whose values should change",
    )


agent = Agent(
    name="Plant Simulation Input Agent",
    instructions=(
        "You update Siemens Plant Simulation parameters. "
        "You will receive a JSON mapping where each top-level key is a parameter name. "
        "Each parameter includes description, route, format, and value. "
        "Use description and format to understand how each value should be written. "
        "Return a JSON object with one field named updates. "
        "updates must be a list of objects with name and value. "
        "Use the exact parameter name from the mapping JSON in name. "
        "Only include parameters whose values should change. "
        "If the user does not mention a parameter, do not include it in updates. "
        "Use values that match the format."
    ),
    output_type=ParameterUpdateResponse,
    model="gpt-5.4-mini",
)
response_agent = Agent(
    name="Plant Simulation Response Agent",
    instructions=(
        "You explain Plant Simulation results to the user. "
        "Use the simulation results provided. "
        "Reply briefly and clearly. Mention the value of line_output."
    ),
    model="gpt-5.4-mini",
)
conversation_agent = Agent(
    name="Plant Simulation Conversation Agent",
    instructions=(
        "You help the user inspect and stage Siemens Plant Simulation parameter changes before a "
        "simulation run. "
        "You will receive the current pending parameter mapping and recent conversation. "
        "Answer questions about current values, available parameters, and what each parameter can "
        "change based on its description and format. "
        "If the user has updated values, acknowledge the new pending values. "
        "Do not say the simulation has run unless simulation results are explicitly provided. "
        "When helpful, remind the user to say 'run simulation' to start the model. "
        "Reply briefly and clearly."
    ),
    model="gpt-5.4-mini",
)

def load_parameter_mapping(filepath: Path) -> dict:
    if filepath.exists():
        return json.loads(filepath.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Parameter mapping file not found: {filepath}")


def load_current_parameter_mapping(mapping_path: Path, parameters_path: Path) -> dict:
    current_mapping = load_parameter_mapping(mapping_path)
    if not parameters_path.exists():
        return current_mapping

    try:
        current_parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return current_mapping

    updated_mapping = deepcopy(current_mapping)
    for parameter_definition in updated_mapping.values():
        route = parameter_definition.get("route")
        if route not in current_parameters:
            continue

        parameter_definition["value"] = _coerce_value(
            current_parameters.get(route),
            parameter_definition.get("value"),
        )

    return updated_mapping


def _coerce_value(candidate_value: Any, default_value: JsonScalar) -> JsonScalar:
    if isinstance(default_value, bool):
        if isinstance(candidate_value, bool):
            return candidate_value
        if isinstance(candidate_value, str):
            lowered = candidate_value.strip().lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
        return default_value

    if isinstance(default_value, int):
        if isinstance(candidate_value, bool):
            return default_value
        if isinstance(candidate_value, int):
            return candidate_value
        if isinstance(candidate_value, float) and candidate_value.is_integer():
            return int(candidate_value)
        if isinstance(candidate_value, str):
            stripped = candidate_value.strip()
            if stripped.lstrip("+-").isdigit():
                return int(stripped)
        return default_value

    if isinstance(default_value, float):
        if isinstance(candidate_value, (int, float)) and not isinstance(candidate_value, bool):
            return float(candidate_value)
        if isinstance(candidate_value, str):
            try:
                return float(candidate_value.strip())
            except ValueError:
                return default_value
        return default_value

    if isinstance(default_value, str):
        if candidate_value is None:
            return default_value
        if isinstance(candidate_value, (str, int, float, bool)):
            return str(candidate_value)
        return default_value

    if default_value is None and isinstance(candidate_value, (str, int, float, bool)):
        return candidate_value

    return default_value


def normalize_parameter_mapping(base_mapping: dict, candidate_mapping: dict) -> dict:
    updated_mapping = deepcopy(base_mapping)

    for candidate_definition in candidate_mapping.get("updates", []):
        if not isinstance(candidate_definition, dict):
            continue

        parameter_name = candidate_definition.get("name")
        if parameter_name not in base_mapping:
            continue

        base_definition = base_mapping[parameter_name]
        updated_mapping[parameter_name]["value"] = _coerce_value(
            candidate_definition.get("value"),
            base_definition.get("value"),
        )

    return updated_mapping


def build_plant_parameter_payload(parameter_mapping: dict) -> dict:
    plant_parameters = {}

    for parameter_definition in parameter_mapping.values():
        route = parameter_definition.get("route")
        if not route:
            continue

        plant_parameters[route] = parameter_definition.get("value")

    return plant_parameters


def _format_conversation_history(conversation_history: list[dict[str, str]], limit: int = 8) -> str:
    if not conversation_history:
        return "No previous conversation."

    formatted_lines = []
    for message in conversation_history[-limit:]:
        formatted_lines.append(f"{message['role'].title()}: {message['content']}")

    return "\n".join(formatted_lines)


def _normalize_command_text(text: str) -> str:
    normalized_text = text.strip().lower()
    for punctuation in ("?", "!", ".", ","):
        normalized_text = normalized_text.replace(punctuation, " ")
    return " ".join(normalized_text.split())


def _should_run_simulation(user_prompt: str) -> bool:
    normalized_prompt = _normalize_command_text(user_prompt)
    if any(negation in normalized_prompt for negation in RUN_SIMULATION_NEGATIONS):
        return False

    for command in RUN_SIMULATION_COMMANDS:
        if any(normalized_prompt.startswith(f"{prefix}{command}") for prefix in RUN_SIMULATION_PREFIXES):
            return True
        if any(f"{joiner}{command}" in normalized_prompt for joiner in RUN_SIMULATION_JOINERS):
            return True

    return False


def _should_exit(user_prompt: str) -> bool:
    return _normalize_command_text(user_prompt) in EXIT_COMMANDS

async def wait_for_simulation_results(timeout_seconds: int) -> dict | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        if RESULTS_PATH.is_file():
            try:
                return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        await asyncio.sleep(0.5)

    return None

async def main() -> str:
    pending_mapping = load_current_parameter_mapping(PARAMETER_MAPPING_FILE, PARAMETERS_PATH)
    conversation_history: list[dict[str, str]] = []

    print("You can inspect or change values first. Say 'run simulation' when you want to start the model. Type 'exit' to quit.")

    while True:
        user_prompt = input("Ask for simulation inputs: ").strip()
        if not user_prompt:
            continue

        if _should_exit(user_prompt):
            return "Session ended."

        recent_history = _format_conversation_history(conversation_history)
        edit_prompt = (
            f"Recent conversation:\n{recent_history}\n\n"
            f"Current pending parameter mapping:\n{json.dumps(pending_mapping, indent=4)}\n\n"
            f"Latest user request:\n{user_prompt}\n\n"
            "Return only the updates list."
        )

        print("Calling Agent")
        edit_result = await Runner.run(agent, edit_prompt)
        pending_mapping = normalize_parameter_mapping(
            pending_mapping,
            edit_result.final_output.model_dump(),
        )

        if _should_run_simulation(user_prompt):
            plant_parameters = build_plant_parameter_payload(pending_mapping)

            print("Writing model_parameters.json and opening model")
            _open_model(plant_parameters)

            results = await wait_for_simulation_results(SIMULATION_TIMEOUT_SECONDS)
            if results is None:
                assistant_reply = "The simulation did not return results."
            else:
                response_prompt = (
                    f"User request:\n{user_prompt}\n\n"
                    f"Updated parameter mapping:\n{json.dumps(pending_mapping, indent=4)}\n\n"
                    f"Plant parameter payload:\n{json.dumps(plant_parameters, indent=4)}\n\n"
                    f"Simulation results:\n{json.dumps(results, indent=4)}\n\n"
                    "Reply to the user in one short sentence. Mention the line_output."
                )

                response_result = await Runner.run(response_agent, response_prompt)
                assistant_reply = response_result.final_output
        else:
            conversation_prompt = (
                f"Recent conversation:\n{recent_history}\n\n"
                f"Current pending parameter mapping:\n{json.dumps(pending_mapping, indent=4)}\n\n"
                f"Latest user request:\n{user_prompt}\n\n"
                "Answer the user. If values were updated in this turn, mention the new pending "
                "values. If the user wants to start the model, tell them to say 'run simulation'."
            )

            response_result = await Runner.run(conversation_agent, conversation_prompt)
            assistant_reply = response_result.final_output

        print(assistant_reply)
        conversation_history.append({"role": "user", "content": user_prompt})
        conversation_history.append({"role": "assistant", "content": assistant_reply})


if __name__ == "__main__":
    print(asyncio.run(main()))
