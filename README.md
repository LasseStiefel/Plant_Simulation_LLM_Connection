# Plant Simulation LLM Connection

This project connects a Siemens Plant Simulation model to a natural-language interface powered by OpenAI. You can chat with the assistant about which parameters exist, inspect their current values, stage changes in conversation, and only start the simulation when you explicitly tell it to run.

## What The Project Does

The current implementation supports a staged conversational workflow:

1. Load parameter definitions from `parameter_mapping.json`.
2. Load the latest active plant values from `model_parameters.json` if they exist.
3. Let the user ask questions such as what can be changed or what the current value is.
4. Let the user stage parameter changes in plain English without immediately launching the model.
5. Start Plant Simulation only when the user gives an explicit run instruction such as `run simulation`.
6. Wait for the simulation to write `model_results.json`.
7. Return a short language summary of the result that mentions `line_output`.

## Current Inputs And Outputs

### Parameter Definition Input

`parameter_mapping.json` is the source of truth for editable parameters. Each parameter entry contains:

- `description`: human-readable explanation of the parameter
- `route`: the Plant Simulation route for the variable
- `format`: guidance for what kind of value the LLM should write
- `value`: the default value used when no prior saved value exists

Example shape:

```json
{
    "Station1ProcTime": {
        "description": "Processing Time of Station 1 in seconds",
        "route": "root.Station1.ProcTime",
        "format": "seconds integer",
        "value": 60
    }
}
```

### Plant Runtime Input

`model_parameters.json` is the simple payload consumed by the Plant Simulation side. It is written only when the user explicitly starts the simulation.

Current format:

```json
{
    "root.Station1.ProcTime": 60,
    "root.Station2.ProcTime": 60,
    "root.AssemblyStation.ProcTime": 60,
    "root.Station3.ProcTime": 60,
    "root.Station3.YDim": 2
}
```

### Simulation Output

The expected simulation result is written to:

- `model_results.json`

The sample result currently included in the repository is:

- `line_output`

## Project Structure

- `agent.py`: shared chat/session logic plus the original terminal entry point
- `model_handling.py`: writes model parameters, launches Plant Simulation, and stores simulation results
- `web_ui.py`: lightweight local web server for the chat UI
- `webui/`: static browser assets for the local chat UI
- `parameter_mapping.json`: parameter definitions used as the LLM's editable-parameter context
- `model_parameters.json`: route-to-value payload written immediately before a simulation run
- `model_results.json`: latest simulation result
- `LLM_Model_V2.spp`: Siemens Plant Simulation model currently launched by Python
- `autoexecute_test.spp`: older Plant Simulation model file still present in the repository
- `autoexecute_test.spp.bak`: backup copy of the older Plant Simulation model
- `plant_inputs.json`: legacy file from the earlier prototype flow; no longer used by the current runtime

## Requirements

- Windows
- Python 3.10 or newer
- Siemens Tecnomatix Plant Simulation installed
- An OpenAI API key

The current code expects Plant Simulation here:

```text
C:\Program Files\Siemens\Tecnomatix Plant Simulation 2504\PlantSimulation.exe
```

If your installation is in a different location or uses a different version, update the `program` path in `model_handling.py`.

## Python Dependencies

The current code uses:

- `openai-agents`
- `python-dotenv`
- `pydantic`

You can install them with:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install openai-agents python-dotenv pydantic
```

## Environment Setup

Create a `.env` file in the project root with:

```env
OPENAI_API_KEY=your_api_key_here
```

`agent.py` loads this value using `python-dotenv`.

## How To Run

### Browser UI

From the project root:

```powershell
.\.venv\Scripts\python.exe web_ui.py
```

Then open:

```text
http://127.0.0.1:8000
```

The browser UI is chat-only on purpose. There is no separate run button yet. Type `run simulation` in the chat when you want to start the model.

### Terminal UI

You can still use the original terminal loop:

```powershell
.\.venv\Scripts\python.exe agent.py
```

You will be prompted with:

```text
Ask for simulation inputs:
```

The session stays open until you type `exit`, `quit`, or `bye`.

## Example Conversation

You can ask informational questions first:

- `what can I change?`
- `what is the current value of station 1?`
- `what does Station3YDim mean?`

You can stage changes without running:

- `set station 1 processing time to 45 seconds`
- `change station 3 capacity to 4`
- `set assembly station processing time to 80`

You can update and run in one message:

- `set station 1 to 45 and run simulation`

Or run later after several staged updates:

- `run simulation`

Questions such as `can we run simulation?` do not start the model. The simulation is only launched on explicit run instructions.

## Runtime Flow

### 1. Pending state initialization

`agent.py` reads `parameter_mapping.json` and builds the current pending parameter state.

If `model_parameters.json` already exists, the pending state is initialized from those saved plant values so the conversation starts from the latest active settings rather than only the defaults.

The same session logic is used by both the terminal mode and the local browser UI.

### 2. Update extraction

An OpenAI agent reads:

- the recent conversation
- the current pending parameter mapping
- the latest user message

It returns a simple structured response of the form:

```json
{
    "updates": [
        {
            "name": "Station1ProcTime",
            "value": 45
        }
    ]
}
```

Python then applies those updates onto the pending parameter mapping and keeps all route, description, and format metadata from `parameter_mapping.json`.

### 3. Conversational guidance

A second conversational agent can answer questions about:

- which parameters can be changed
- what their current pending values are
- what a parameter means based on `description`
- what type of value is expected based on `format`

This allows a normal back-and-forth chat before running the model.

### 4. Plant payload creation

When the user gives an explicit run instruction, Python converts the pending mapping into a simple plant-facing payload:

```json
{
    "root.Station1.ProcTime": 45,
    "root.Station2.ProcTime": 60
}
```

That route-to-value payload is written to `model_parameters.json`.

### 5. Simulation launch

`model_handling._open_model()`:

- writes the plant payload to `model_parameters.json`
- deletes any stale `model_results.json`
- launches `LLM_Model_V2.spp` with Plant Simulation

### 6. Result collection

`agent.py` waits up to 300 seconds for `model_results.json` to appear and contain valid JSON.

### 7. User-facing response

A response agent reads the simulation results and returns a short explanation that includes `line_output`.

## Important Notes

- `parameter_mapping.json` is the LLM-facing source of truth for parameter names, descriptions, formats, and default values.
- `model_parameters.json` is the Plant Simulation-facing payload and currently uses the shape `{route: value}`.
- Pending values are updated during the conversation, but `model_parameters.json` is only rewritten when the user explicitly starts a simulation run.
- The local browser UI is intentionally minimal and keeps the interaction pure chat. Typing `run simulation` still controls execution.
- The current runtime uses `gpt-5.4-mini` for the update, conversation, and response agents.
- The timeout for waiting on simulation results is currently 300 seconds.
- This project assumes the `.spp` model is configured to read `model_parameters.json` and write `model_results.json` during execution.

## Typical Use Case

This repository is useful as a lightweight prototype for:

- translating natural-language requests into simulation parameter changes
- discussing editable simulation parameters before committing a run
- staging several changes across a short conversation
- launching Plant Simulation from Python only on explicit user instruction
- returning simulation outcomes in plain language

## Possible Next Improvements

- add `requirements.txt` or `pyproject.toml`
- persist staged conversation state across restarts
- add validation rules beyond simple type coercion
- make the Plant Simulation executable path configurable
- log simulation runs and staged parameter changes
- add tests around command detection, JSON handling, and timeout behavior
