# Plant Simulation LLM Connection

Local chat interface for configuring a Siemens Plant Simulation model with an LLM.

## Run

Web UI:
```powershell
.\.venv\Scripts\python.exe web_ui.py
```
Open `http://127.0.0.1:8000`

Terminal chat:
```powershell
.\.venv\Scripts\python.exe agent.py
```

## Main Files

- `agent.py`: main LLM prompts and terminal entry point
- `session.py`: shared chat/session logic
- `web_ui.py`: local web server
- `model_handling.py`: writes inputs and launches `LLM_Model_V2.spp`
- `pltsim.py`: Plant Simulation Python module bridge
- `parameter_mapping.json`: editable parameter definitions for the LLM
- `model_parameters.json`: plant-facing `{route: value}` payload
- `model_results.json`: latest simulation output
- `pltsim.png`: image of the Plant Simulation model

## Parameter Mapping

`parameter_mapping.json` is the source of truth for what the user can change.
Each entry contains:

- `description`: what the variable means
- `route`: the Plant Simulation variable path
- `format`: how the value should be written
- `value`: the current/default value

Example:
```json
"Station1ProcTime": {
  "description": "Processing Time of Station 1 in seconds",
  "route": "root.Station1.ProcTime",
  "format": "seconds integer",
  "value": 60
}
```

## LLM Output Contract

The LLM uses the mapping as context and returns a small JSON object:

```json
{
  "reply": "Natural reply to the user",
  "updates": [{"name": "Station1ProcTime", "value": 75}],
  "should_run": false
}
```

`updates` changes staged values by parameter name. `should_run` controls whether the simulation should start.

## Flow

1. The session loads `parameter_mapping.json`.
2. The LLM answers questions and stages updates against those parameters.
3. The session converts the staged mapping into `model_parameters.json` as `{route: value}`.
4. `model_handling.py` opens `LLM_Model_V2.spp`.
5. Inside Plant Simulation, `pltsim.py` reads `model_parameters.json` and applies each variable with:
   `exec(f"{route} = {repr(value)}", globals(), locals())`
6. After the run, `pltsim.py` sends results back through `_send_sim_results(...)`.
7. The app reads `model_results.json` and summarizes the result in chat.

## Notes

- The UI is chat-only. There is no run button.
- The variable viewer is a hidden drawer on the right.
- If the user is still exploring values, the assistant should ask before running.
- Current simulation results include `line_output`.
