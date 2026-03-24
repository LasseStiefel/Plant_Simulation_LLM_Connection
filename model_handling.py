import json
from pathlib import Path

import subprocess

BASE_DIR = Path(__file__).resolve().parent
program = r"C:\Program Files\Siemens\Tecnomatix Plant Simulation 2504\PlantSimulation.exe"
file_path = BASE_DIR / "LLM_Model_V2.spp"

PARAMETER_MAPPING_PATH = BASE_DIR / "parameter_mapping.json"
PARAMETERS_PATH = BASE_DIR / "model_parameters.json"
RESULTS_PATH = BASE_DIR / "model_results.json"

_ACTIVE_WAITER = None

def _mapping_to_plant_payload(parameter_mapping: dict) -> dict:
    plant_parameters = {}

    for parameter_definition in parameter_mapping.values():
        route = parameter_definition.get("route")
        if not route:
            continue

        plant_parameters[route] = parameter_definition.get("value")

    return plant_parameters


def _default_state():
    if PARAMETER_MAPPING_PATH.is_file():
        with PARAMETER_MAPPING_PATH.open("r", encoding="utf-8") as f:
            return _mapping_to_plant_payload(json.load(f))

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
