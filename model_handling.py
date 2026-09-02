import json
from pathlib import Path

import subprocess
from session import build_plant_parameter_payload, load_optional_json_object, load_parameter_mapping

BASE_DIR = Path(__file__).resolve().parent
program = r"C:\Program Files\Siemens\Tecnomatix Plant Simulation 2504\PlantSimulation.exe"
file_path = BASE_DIR / "LLM_Model_V2.spp"

PARAMETER_MAPPING_PATH = BASE_DIR / "parameter_mapping.json"
FORMAT_INSTRUCTIONS_PATH = BASE_DIR / "format_instructions.json"
PARAMETERS_PATH = BASE_DIR / "model_parameters.json"
RESULTS_PATH = BASE_DIR / "model_results.json"

_ACTIVE_WAITER = None


def _default_state():
    if PARAMETER_MAPPING_PATH.is_file():
        format_instructions = load_optional_json_object(FORMAT_INSTRUCTIONS_PATH)
        parameter_mapping = load_parameter_mapping(PARAMETER_MAPPING_PATH)
        return build_plant_parameter_payload(parameter_mapping, format_instructions)

    return {
        "root.Store1ProcTime": 60,
        "root.Store2ProcTime": 60,
    }

def _save_parameters(parameters: dict) -> None:
    PARAMETERS_PATH.write_text(json.dumps(parameters, indent=4), encoding="utf-8")

def _load_parameters() -> dict:
    if PARAMETERS_PATH.is_file():
        with PARAMETERS_PATH.open("r", encoding="utf-8") as f:
            parameters = json.load(f)
    else:
        parameters = _default_state()

    return parameters

def _get_param() -> dict: #dict
    parameters = _load_parameters()

    return parameters

def _open_model(updated_json: dict, waiter=None) -> None:
    global _ACTIVE_WAITER

    _ACTIVE_WAITER = waiter
    _save_parameters(updated_json)
    if RESULTS_PATH.exists():
        RESULTS_PATH.unlink()

    # Open Model
    subprocess.Popen([program, str(file_path)])

def _send_sim_results(simulation_results: dict) -> None:
    global _ACTIVE_WAITER

    RESULTS_PATH.write_text(json.dumps(simulation_results, indent=4), encoding="utf-8")

    if _ACTIVE_WAITER is not None:
        _ACTIVE_WAITER.results = simulation_results
        _ACTIVE_WAITER.done.set()
        _ACTIVE_WAITER = None
