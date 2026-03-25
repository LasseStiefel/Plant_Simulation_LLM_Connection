import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Awaitable, Callable, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
TurnRunner: TypeAlias = Callable[[list[dict[str, str]], dict, str, dict | None], Awaitable[dict]]
ResultSummarizer: TypeAlias = Callable[[list[dict[str, str]], str, dict, dict, dict, str], Awaitable[str]]
ModelOpener: TypeAlias = Callable[[dict], None]


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

        candidate_value = current_parameters.get(route)
        default_value = parameter_definition.get("value")
        if is_valid_value_for_default(candidate_value, default_value):
            parameter_definition["value"] = candidate_value

    return updated_mapping


def build_plant_parameter_payload(parameter_mapping: dict) -> dict:
    plant_parameters = {}

    for parameter_definition in parameter_mapping.values():
        route = parameter_definition.get("route")
        if not route:
            continue

        plant_parameters[route] = parameter_definition.get("value")

    return plant_parameters


def format_conversation_history(conversation_history: list[dict[str, str]], limit: int = 8) -> str:
    if not conversation_history:
        return "[]"

    return json.dumps(conversation_history[-limit:], indent=4)


def is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def is_valid_value_for_default(candidate_value: object, default_value: JsonScalar) -> bool:
    if not is_json_scalar(candidate_value):
        return False

    if isinstance(default_value, bool):
        return isinstance(candidate_value, bool)

    if isinstance(default_value, int):
        return isinstance(candidate_value, int) and not isinstance(candidate_value, bool)

    if isinstance(default_value, float):
        return isinstance(candidate_value, (int, float)) and not isinstance(candidate_value, bool)

    if isinstance(default_value, str):
        return isinstance(candidate_value, str)

    if default_value is None:
        return True

    return False


def apply_updates(parameter_mapping: dict, updates: list[dict]) -> tuple[dict, list[str]]:
    updated_mapping = deepcopy(parameter_mapping)
    invalid_updates: list[str] = []

    for update in updates:
        if not isinstance(update, dict):
            continue

        parameter_name = update.get("name")
        if parameter_name not in updated_mapping:
            if isinstance(parameter_name, str):
                invalid_updates.append(parameter_name)
            continue

        candidate_value = update.get("value")
        default_value = updated_mapping[parameter_name].get("value")
        if not is_valid_value_for_default(candidate_value, default_value):
            invalid_updates.append(parameter_name)
            continue

        updated_mapping[parameter_name]["value"] = candidate_value

    return updated_mapping, invalid_updates


def build_invalid_update_note(invalid_updates: list[str]) -> str:
    if not invalid_updates:
        return ""

    count = len(invalid_updates)
    if count == 1:
        return "I kept one suggested value unchanged because it did not match the expected type."

    return f"I kept {count} suggested values unchanged because they did not match the expected types."


async def wait_for_simulation_results(results_path: Path, timeout_seconds: int) -> dict | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        if results_path.is_file():
            try:
                return json.loads(results_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        await asyncio.sleep(0.5)

    return None


class PlantSimulationSession:
    def __init__(
        self,
        *,
        mapping_path: Path,
        parameters_path: Path,
        results_path: Path,
        open_model: ModelOpener,
        run_turn: TurnRunner,
        summarize_results: ResultSummarizer | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.mapping_path = mapping_path
        self.parameters_path = parameters_path
        self.results_path = results_path
        self.open_model = open_model
        self.run_turn = run_turn
        self.summarize_results = summarize_results
        self.timeout_seconds = timeout_seconds
        self.pending_mapping = load_current_parameter_mapping(mapping_path, parameters_path)
        self.conversation_history: list[dict[str, str]] = []
        self.last_simulation_context: dict | None = None

    def snapshot(self) -> dict:
        return {
            "pending_mapping": deepcopy(self.pending_mapping),
            "history": deepcopy(self.conversation_history),
        }

    async def handle_message(self, user_prompt: str) -> dict:
        user_prompt = user_prompt.strip()
        if not user_prompt:
            return {
                "reply": "Please enter a message.",
                "state": self.snapshot(),
                "ran_simulation": False,
            }

        turn_output = await self.run_turn(
            self.conversation_history,
            self.pending_mapping,
            user_prompt,
            self.last_simulation_context,
        )
        reply = str(turn_output.get("reply", "")).strip() or "Okay."
        updates = turn_output.get("updates", [])
        should_run = bool(turn_output.get("should_run", False))

        self.pending_mapping, invalid_updates = apply_updates(self.pending_mapping, updates)
        invalid_note = build_invalid_update_note(invalid_updates)
        if invalid_note:
            reply = f"{reply}\n\n{invalid_note}"

        ran_simulation = False
        if should_run:
            ran_simulation = True
            plant_parameters = build_plant_parameter_payload(self.pending_mapping)
            self.open_model(plant_parameters)

            results = await wait_for_simulation_results(self.results_path, self.timeout_seconds)
            if results is None:
                reply = f"{reply}\n\nThe simulation did not return results."
            elif self.summarize_results is not None:
                self.last_simulation_context = {
                    "pending_mapping": deepcopy(self.pending_mapping),
                    "plant_parameters": deepcopy(plant_parameters),
                    "results": deepcopy(results),
                }
                reply = await self.summarize_results(
                    self.conversation_history,
                    user_prompt,
                    self.pending_mapping,
                    plant_parameters,
                    results,
                    reply,
                )

        self.conversation_history.append({"role": "user", "content": user_prompt})
        self.conversation_history.append({"role": "assistant", "content": reply})
        return {
            "reply": reply,
            "state": self.snapshot(),
            "ran_simulation": ran_simulation,
        }
