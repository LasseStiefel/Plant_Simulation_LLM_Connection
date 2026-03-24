# Plant Simulation LLM Connection

Local chat interface for configuring a Siemens Plant Simulation model with an LLM.

## Run

Web UI:

```powershell
.\.venv\Scripts\python.exe web_ui.py
```

Then open `http://127.0.0.1:8000`

Terminal chat:

```powershell
.\.venv\Scripts\python.exe agent.py
```

## Main Files

- `agent.py`: thin LLM entry point and terminal chat runner
- `session.py`: shared chat/session logic used by both terminal and web UI
- `web_ui.py`: local web server for the chat interface
- `model_handling.py`: writes plant inputs and launches the Plant Simulation model
- `parameter_mapping.json`: source of truth for editable parameters
- `model_parameters.json`: plant-facing `{route: value}` payload
- `model_results.json`: latest simulation output written by the model

## How It Works

1. The LLM uses `parameter_mapping.json` as context for parameter names, descriptions, formats, routes, and default values.
2. Changes are staged in the session until the model decides the user is clearly asking to run the simulation.
3. When a run starts, the system writes `model_parameters.json` in `{route: value}` format and opens `LLM_Model_V2.spp`.
4. The app waits for `model_results.json` and then summarizes the result in chat.

## Notes

- The web UI is chat-only. There is no run button.
- The variable viewer is available in the UI as a hidden right-side drawer.
- If the user is still exploring values, the assistant should ask before running.
