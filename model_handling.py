import json
from pathlib import Path

import subprocess

BASE_DIR = Path(__file__).resolve().parent
program = r"C:\Program Files\Siemens\Tecnomatix Plant Simulation 2504\PlantSimulation.exe"
file_path = BASE_DIR / "autoexecute_test.spp"



PARAMETERS_PATH = BASE_DIR / "model_parameters.json"
RESULTS_PATH = BASE_DIR / "model_results.json"

_ACTIVE_WAITER = None

def _default_state():
    return{
        "Store1ProcTime": 60,
        "Store2ProcTime": 60
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


def _get_param() -> int: #dict
    parameters = _load_parameters()
    Store1ProcTime = parameters["Store1ProcTime"]
    Store2ProcTime = parameters["Store2ProcTime"]

    return Store1ProcTime, Store2ProcTime

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

