import asyncio
import json
from pathlib import Path

from agents import Agent, AgentOutputSchema, Runner
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from model_handling import PARAMETERS_PATH, RESULTS_PATH, _open_model
from session import (
    JsonValue,
    PlantSimulationSession,
    build_parameter_context_for_llm,
    format_conversation_history,
    load_optional_json_object,
)

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent
PARAMETER_MAPPING_FILE = BASE_DIR / "parameter_mapping.json"
FORMAT_INSTRUCTIONS_FILE = BASE_DIR / "format_instructions.json"
GENERAL_KNOWLEDGE_FILE = BASE_DIR / "general_knowledge.json"
SIMULATION_TIMEOUT_SECONDS = 300


class ParameterValueUpdate(BaseModel):
    name: str = Field(description="Exact parameter name from the mapping JSON")
    value: JsonValue = Field(
        description=(
            "The new staged value for that parameter. Use a scalar for normal direct-route "
            "parameters. Use an object of component names to scalar values for component-based "
            "time parameters."
        )
    )


class TurnResponse(BaseModel):
    reply: str = Field(description="Natural conversational reply to the user")
    updates: list[ParameterValueUpdate] = Field(
        default_factory=list,
        description="Only include parameters whose values should change in this turn",
    )
    should_run: bool = Field(
        description="True only when the user is clearly asking to run the simulation now",
    )


turn_agent = Agent(
    name="Plant Simulation Turn Agent",
    instructions=(
        "You are helping a user configure a Siemens Plant Simulation model through chat. "
        "You will receive recent conversation, general knowledge, format instructions, the current pending parameter mapping, the latest user message, and optionally the most recent simulation context. "
        "Each parameter in the mapping includes description, format, route, current value, and may include format-specific guidance. "
        "Use this information to answer questions naturally, stage value changes, answer questions about the most recent simulation result when context is provided, and decide whether the simulation should run now. "
        "Return three things: reply, updates, and should_run. "
        "Write reply in plain natural prose and keep it brief for simple questions. "
        "Only include parameters in updates when their value should change in this turn. "
        "Use the exact parameter names from the mapping JSON. "
        "Never return null for a parameter value. If the user has not specified a value yet, keep the current value or use the mapping default instead of null. "
        "For normal direct-route parameters, set value as a scalar. "
        "For time parameters, if the selected timetype requires component routes, set value as an object whose keys are the component names shown in the parameter context. "
        "If a time parameter uses the default direct route, set value as a scalar instead of an object. "
        "When a user changes a timetype, keep the paired time parameter consistent with that timetype. "
        "Set should_run to true only when the user clearly wants to start the simulation now or is clearly done configuring and asking to proceed. "
        "Do not run the simulation on every user input. "
        "If you are unsure whether they want to run now, ask them directly in reply and set should_run to false. "
        "When the user is still exploring values or asking questions, keep should_run false. "
        "When the user asks about the most recent simulation result, answer from that context if it is provided. "
        "Avoid markdown-heavy formatting for simple answers."
    ),
    output_type=AgentOutputSchema(TurnResponse, strict_json_schema=False),
    model="gpt-5.4-mini",
)

result_summary_agent = Agent(
    name="Plant Simulation Result Summary Agent",
    instructions=(
        "You explain finished Plant Simulation results to the user in natural prose. "
        "Use the user's request and the recent conversation to choose the right level of detail. "
        "If the user asks for more explanation, provide more explanation instead of a fixed short template. "
        "Mention the value of line_output when available, but do not answer with labels or snippets like 'output = 560'. "
        "Do not use markdown bold, bullet points, or code formatting unless the user asks for them. "
        "Connect the result to the configured parameters when that helps answer the user's question. "
        "If only limited simulation metrics are available, say that clearly instead of inventing details."
    ),
    model="gpt-5.4-mini",
)


async def run_turn_agent(
    conversation_history: list[dict[str, str]],
    pending_mapping: dict,
    user_prompt: str,
    last_simulation_context: dict | None,
) -> dict:
    format_instructions = load_optional_json_object(FORMAT_INSTRUCTIONS_FILE)
    general_knowledge = load_optional_json_object(GENERAL_KNOWLEDGE_FILE)
    prompt_mapping = build_parameter_context_for_llm(pending_mapping, format_instructions)
    prompt = (
        f"Recent conversation:\n{format_conversation_history(conversation_history)}\n\n"
        f"General knowledge:\n{json.dumps(general_knowledge, indent=4)}\n\n"
        f"Format instructions:\n{json.dumps(format_instructions, indent=4)}\n\n"
        f"Current pending parameter mapping:\n{json.dumps(prompt_mapping, indent=4)}\n\n"
        f"Most recent simulation context:\n{json.dumps(last_simulation_context, indent=4) if last_simulation_context else 'None'}\n\n"
        f"Latest user request:\n{user_prompt}"
    )
    result = await Runner.run(turn_agent, prompt)
    return result.final_output.model_dump()


async def summarize_results(
    conversation_history: list[dict[str, str]],
    user_prompt: str,
    pending_mapping: dict,
    plant_parameters: dict,
    results: dict,
    initial_reply: str,
) -> str:
    general_knowledge = load_optional_json_object(GENERAL_KNOWLEDGE_FILE)
    prompt = (
        f"Recent conversation:\n{format_conversation_history(conversation_history)}\n\n"
        f"General knowledge:\n{json.dumps(general_knowledge, indent=4)}\n\n"
        f"User request:\n{user_prompt}\n\n"
        f"Assistant reply before running:\n{initial_reply}\n\n"
        f"Updated parameter mapping:\n{json.dumps(pending_mapping, indent=4)}\n\n"
        f"Plant parameter payload:\n{json.dumps(plant_parameters, indent=4)}\n\n"
        f"Simulation results:\n{json.dumps(results, indent=4)}"
    )
    result = await Runner.run(result_summary_agent, prompt)
    return result.final_output


def create_session() -> PlantSimulationSession:
    return PlantSimulationSession(
        mapping_path=PARAMETER_MAPPING_FILE,
        parameters_path=PARAMETERS_PATH,
        results_path=RESULTS_PATH,
        open_model=_open_model,
        run_turn=run_turn_agent,
        format_instructions_path=FORMAT_INSTRUCTIONS_FILE,
        summarize_results=summarize_results,
        timeout_seconds=SIMULATION_TIMEOUT_SECONDS,
    )


async def main() -> None:
    session = create_session()
    print("Ask about values, stage changes, and tell me when you want to run the simulation.")

    while True:
        user_prompt = input("Ask for simulation inputs: ").strip()
        if not user_prompt:
            continue

        if user_prompt.lower() in {"exit", "quit", "bye"}:
            print("Session ended.")
            return

        result = await session.handle_message(user_prompt)
        print(result["reply"])


if __name__ == "__main__":
    asyncio.run(main())
