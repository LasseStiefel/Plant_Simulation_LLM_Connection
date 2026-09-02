import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Awaitable, Callable, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool
JsonObjectValue: TypeAlias = dict[str, JsonScalar]
JsonValue: TypeAlias = JsonScalar | JsonObjectValue
TurnRunner: TypeAlias = Callable[[list[dict[str, str]], dict, str, dict | None], Awaitable[dict]]
ResultSummarizer: TypeAlias = Callable[[list[dict[str, str]], str, dict, dict, dict, str], Awaitable[str]]
ModelOpener: TypeAlias = Callable[[dict], None]


def load_parameter_mapping(filepath: Path) -> dict:
    if filepath.exists():
        return json.loads(filepath.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Parameter mapping file not found: {filepath}")


def load_optional_json_object(filepath: Path | None) -> dict:
    if filepath is None or not filepath.exists():
        return {}

    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    return data if isinstance(data, dict) else {}


def flatten_string_entries(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []

    flattened: list[str] = []
    for item in value:
        flattened.extend(flatten_string_entries(item))
    return flattened


def get_format_definition(format_instructions: dict, format_name: str | None) -> dict:
    if not isinstance(format_name, str):
        return {}

    definition = format_instructions.get(format_name)
    return definition if isinstance(definition, dict) else {}


def get_timetype_options(format_instructions: dict) -> list[str]:
    timetype_definition = get_format_definition(format_instructions, "timetype")
    raw_output = timetype_definition.get("output")
    if not isinstance(raw_output, list):
        return []

    options: list[str] = []
    for entry in raw_output:
        options.extend(flatten_string_entries(entry))
    return options


def get_time_output_keys_by_timetype(format_instructions: dict) -> dict[str, list[str]]:
    time_definition = get_format_definition(format_instructions, "time")
    timetype_definition = get_format_definition(format_instructions, "timetype")
    raw_time_output = time_definition.get("output")
    raw_timetype_output = timetype_definition.get("output")
    if not isinstance(raw_time_output, list) or not isinstance(raw_timetype_output, list):
        return {}

    output_keys_by_timetype: dict[str, list[str]] = {}
    for index, raw_timetype_entry in enumerate(raw_timetype_output):
        timetype_names = flatten_string_entries(raw_timetype_entry)
        raw_time_entry = raw_time_output[index] if index < len(raw_time_output) else []
        component_keys = [
            key for key in flatten_string_entries(raw_time_entry) if isinstance(key, str) and key.strip()
        ]
        for timetype_name in timetype_names:
            output_keys_by_timetype[timetype_name] = component_keys

    return output_keys_by_timetype


def find_time_dependency_parameter(parameter_name: str, parameter_mapping: dict) -> str | None:
    candidate_names = [f"{parameter_name}Type"]

    for candidate_name in candidate_names:
        candidate_definition = parameter_mapping.get(candidate_name)
        if not isinstance(candidate_definition, dict):
            continue
        if candidate_definition.get("format") == "timetype":
            return candidate_name

    return None


def get_selected_timetype(parameter_name: str, parameter_mapping: dict) -> str | None:
    dependency_name = find_time_dependency_parameter(parameter_name, parameter_mapping)
    if dependency_name is None:
        return None

    candidate_value = parameter_mapping.get(dependency_name, {}).get("value")
    return candidate_value if isinstance(candidate_value, str) else None


def get_time_component_keys(
    parameter_name: str,
    parameter_mapping: dict,
    format_instructions: dict,
) -> list[str]:
    selected_timetype = get_selected_timetype(parameter_name, parameter_mapping)
    if not selected_timetype:
        return []

    return get_time_output_keys_by_timetype(format_instructions).get(selected_timetype, [])


def normalize_time_component_route_suffix(component_name: str) -> str:
    stripped = component_name.strip()
    if stripped.lower() == "lambda":
        return "lambda"
    return stripped


def is_proc_time_type_route(route: object) -> bool:
    if not isinstance(route, str):
        return False

    normalized = "".join(character for character in route.lower() if character.isalnum())
    return "proctimetype" in normalized


def sort_plant_parameter_payload(plant_parameters: dict) -> dict:
    prioritized_items: list[tuple[str, JsonValue]] = []
    other_items: list[tuple[str, JsonValue]] = []

    for route, value in plant_parameters.items():
        if is_proc_time_type_route(route):
            prioritized_items.append((route, value))
        else:
            other_items.append((route, value))

    return dict(prioritized_items + other_items)


def build_parameter_context_for_llm(parameter_mapping: dict, format_instructions: dict) -> dict:
    enriched_mapping = deepcopy(parameter_mapping)
    time_output_keys_by_timetype = get_time_output_keys_by_timetype(format_instructions)
    timetype_options = get_timetype_options(format_instructions)

    for parameter_name, parameter_definition in enriched_mapping.items():
        if not isinstance(parameter_definition, dict):
            continue

        format_name = parameter_definition.get("format")
        format_definition = get_format_definition(format_instructions, format_name)
        if format_definition:
            parameter_definition["format_details"] = deepcopy(format_definition)

        if format_name == "time":
            dependency_name = find_time_dependency_parameter(parameter_name, parameter_mapping)
            parameter_definition["resolved_value_shape"] = (
                "Use a scalar for the default route. "
                "Use an object of component names to scalar values when the selected timetype "
                "requires component routes."
            )
            parameter_definition["dependent_timetype_parameter"] = dependency_name
            if dependency_name is not None:
                parameter_definition["dependent_timetype_value"] = parameter_mapping.get(
                    dependency_name, {}
                ).get("value")
            if time_output_keys_by_timetype:
                parameter_definition["time_output_keys_by_timetype"] = deepcopy(
                    time_output_keys_by_timetype
                )

        if format_name == "timetype" and timetype_options:
            parameter_definition["allowed_values"] = timetype_options

    return enriched_mapping


def load_current_parameter_mapping(
    mapping_path: Path,
    parameters_path: Path,
    format_instructions: dict | None = None,
) -> dict:
    format_instructions = format_instructions or {}
    current_mapping = load_parameter_mapping(mapping_path)
    updated_mapping = deepcopy(current_mapping)
    for parameter_definition in updated_mapping.values():
        default_value = get_parameter_default_value(parameter_definition)
        if default_value is not None:
            parameter_definition["value"] = default_value

    if not parameters_path.exists():
        return updated_mapping

    try:
        current_parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return updated_mapping

    for parameter_definition in updated_mapping.values():
        route = parameter_definition.get("route")
        if route not in current_parameters:
            continue

        candidate_value = current_parameters.get(route)
        default_value = get_parameter_default_value(parameter_definition)
        if is_valid_value_for_default(candidate_value, default_value):
            parameter_definition["value"] = candidate_value

    for parameter_name, parameter_definition in updated_mapping.items():
        if parameter_definition.get("format") != "time":
            continue

        route = parameter_definition.get("route")
        if not isinstance(route, str) or not route:
            continue

        component_keys = get_time_component_keys(parameter_name, updated_mapping, format_instructions)
        if not component_keys:
            continue

        component_values: JsonObjectValue = {}
        for component_key in component_keys:
            component_route = f"{route}.{normalize_time_component_route_suffix(component_key)}"
            if component_route not in current_parameters:
                continue

            candidate_value = current_parameters.get(component_route)
            if is_json_scalar(candidate_value):
                component_values[component_key] = candidate_value

        if component_values:
            parameter_definition["value"] = component_values

    return updated_mapping


def build_plant_parameter_payload(parameter_mapping: dict, format_instructions: dict | None = None) -> dict:
    format_instructions = format_instructions or {}
    plant_parameters = {}

    for parameter_name, parameter_definition in parameter_mapping.items():
        route = parameter_definition.get("route")
        if not route:
            continue

        format_name = parameter_definition.get("format")
        value = get_parameter_value_or_default(parameter_definition)
        default_scalar_value = get_parameter_default_value(parameter_definition)
        if format_name == "time":
            component_keys = get_time_component_keys(parameter_name, parameter_mapping, format_instructions)
            if component_keys and is_json_object_value(value):
                for component_key in component_keys:
                    component_route = f"{route}.{normalize_time_component_route_suffix(component_key)}"
                    component_value = value.get(component_key, default_scalar_value)
                    if component_value is None:
                        continue
                    plant_parameters[component_route] = component_value
                continue

            if component_keys and is_json_scalar(value):
                for component_key in component_keys:
                    component_route = f"{route}.{normalize_time_component_route_suffix(component_key)}"
                    plant_parameters[component_route] = value
                continue

            if not component_keys and is_json_object_value(value):
                if "" in value:
                    plant_parameters[route] = value[""]
                else:
                    scalar_values = [candidate for candidate in value.values() if is_json_scalar(candidate)]
                    if scalar_values:
                        plant_parameters[route] = scalar_values[0]
                    elif default_scalar_value is not None:
                        plant_parameters[route] = default_scalar_value
                continue

        if is_json_scalar(value):
            plant_parameters[route] = value

    return sort_plant_parameter_payload(plant_parameters)


def format_conversation_history(conversation_history: list[dict[str, str]], limit: int = 8) -> str:
    if not conversation_history:
        return "[]"

    return json.dumps(conversation_history[-limit:], indent=4)


def is_json_scalar(value: object) -> bool:
    return isinstance(value, (str, int, float, bool))


def is_json_object_value(value: object) -> bool:
    if not isinstance(value, dict):
        return False

    return all(isinstance(key, str) and is_json_scalar(item) for key, item in value.items())


def get_parameter_default_value(parameter_definition: dict) -> JsonScalar | None:
    candidate_default = parameter_definition.get("default")
    return candidate_default if is_json_scalar(candidate_default) else None


def get_parameter_value_or_default(parameter_definition: dict) -> JsonValue | None:
    candidate_value = parameter_definition.get("value")
    if is_json_scalar(candidate_value) or is_json_object_value(candidate_value):
        return candidate_value

    return get_parameter_default_value(parameter_definition)


def is_valid_value_for_default(candidate_value: object, default_value: JsonScalar | None) -> bool:
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


def is_valid_time_value(
    parameter_name: str,
    candidate_value: object,
    parameter_mapping: dict,
    format_instructions: dict,
) -> bool:
    if is_json_scalar(candidate_value):
        return True

    if not is_json_object_value(candidate_value):
        return False

    component_keys = get_time_component_keys(parameter_name, parameter_mapping, format_instructions)
    if not component_keys:
        return True

    return set(candidate_value).issubset(set(component_keys))


def is_valid_timetype_value(candidate_value: object, format_instructions: dict) -> bool:
    if not isinstance(candidate_value, str):
        return False

    options = get_timetype_options(format_instructions)
    if not options:
        return True

    return candidate_value in options


def is_valid_value_for_parameter(
    parameter_name: str,
    parameter_definition: dict,
    candidate_value: object,
    parameter_mapping: dict,
    format_instructions: dict,
) -> bool:
    format_name = parameter_definition.get("format")
    if format_name == "time":
        return is_valid_time_value(parameter_name, candidate_value, parameter_mapping, format_instructions)

    if format_name == "timetype":
        return is_valid_timetype_value(candidate_value, format_instructions)

    if format_name == "boolean":
        return isinstance(candidate_value, bool)

    if format_name == "machinecapacity":
        return isinstance(candidate_value, int) and not isinstance(candidate_value, bool)

    default_value = get_parameter_default_value(parameter_definition)
    if is_json_scalar(candidate_value):
        return is_valid_value_for_default(candidate_value, default_value)

    return False


def apply_updates(
    parameter_mapping: dict,
    updates: list[dict],
    format_instructions: dict | None = None,
) -> tuple[dict, list[str]]:
    format_instructions = format_instructions or {}
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
        parameter_definition = updated_mapping[parameter_name]
        if not is_valid_value_for_parameter(
            parameter_name,
            parameter_definition,
            candidate_value,
            updated_mapping,
            format_instructions,
        ):
            invalid_updates.append(parameter_name)
            continue

        existing_value = parameter_definition.get("value")
        if (
            parameter_definition.get("format") == "time"
            and is_json_object_value(existing_value)
            and is_json_object_value(candidate_value)
        ):
            merged_value = dict(existing_value)
            merged_value.update(candidate_value)
            parameter_definition["value"] = merged_value
        else:
            parameter_definition["value"] = candidate_value

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
        format_instructions_path: Path | None = None,
        summarize_results: ResultSummarizer | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.mapping_path = mapping_path
        self.parameters_path = parameters_path
        self.results_path = results_path
        self.open_model = open_model
        self.run_turn = run_turn
        self.format_instructions_path = format_instructions_path
        self.format_instructions = load_optional_json_object(format_instructions_path)
        self.summarize_results = summarize_results
        self.timeout_seconds = timeout_seconds
        self.pending_mapping = load_current_parameter_mapping(
            mapping_path,
            parameters_path,
            self.format_instructions,
        )
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

        self.format_instructions = load_optional_json_object(self.format_instructions_path)

        turn_output = await self.run_turn(
            self.conversation_history,
            self.pending_mapping,
            user_prompt,
            self.last_simulation_context,
        )
        reply = str(turn_output.get("reply", "")).strip() or "Okay."
        updates = turn_output.get("updates", [])
        should_run = bool(turn_output.get("should_run", False))

        self.pending_mapping, invalid_updates = apply_updates(
            self.pending_mapping,
            updates,
            self.format_instructions,
        )
        invalid_note = build_invalid_update_note(invalid_updates)
        if invalid_note:
            reply = f"{reply}\n\n{invalid_note}"

        ran_simulation = False
        if should_run:
            ran_simulation = True
            plant_parameters = build_plant_parameter_payload(
                self.pending_mapping,
                self.format_instructions,
            )
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
