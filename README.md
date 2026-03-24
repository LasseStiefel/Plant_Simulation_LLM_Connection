# Plant Simulation LLM Connection

This project connects a Siemens Plant Simulation model to a natural-language interface powered by OpenAI. A user describes desired simulation changes in plain English, the Python app converts that request into structured parameters, launches the Plant Simulation model, waits for the simulation to finish, and returns a short language summary of the result.

## What The Project Does

The current implementation supports a simple end-to-end loop:

1. Read the latest input values from `plant_inputs.json`.
2. Ask an OpenAI agent to update `Store1ProcTime` and `Store2ProcTime` from a user prompt.
3. Save the updated values to JSON.
4. Launch `autoexecute_test.spp` in Siemens Plant Simulation.
5. Wait for the simulation to write results to `model_results.json`.
6. Ask a second OpenAI agent to summarize the result and mention `line_output`.

## Current Inputs And Outputs

### Inputs

The active Python flow currently exposes two integer parameters:

- `Store1ProcTime`
- `Store2ProcTime`

These are stored in:

- `plant_inputs.json`: latest user-facing values
- `model_parameters.json`: values written immediately before launching the simulation

### Output

The expected simulation result is written to:

- `model_results.json`

The sample result currently included in the repository is:

- `line_output`

## Project Structure

- `agent.py`: main entry point; handles user input, agent calls, JSON updates, and waiting for simulation output
- `model_handling.py`: writes model parameters, launches Plant Simulation, and stores simulation results
- `autoexecute_test.spp`: Siemens Plant Simulation model
- `autoexecute_test.spp.bak`: backup copy of the Plant Simulation model
- `plant_inputs.json`: latest requested inputs
- `model_parameters.json`: parameters consumed by the simulation
- `model_results.json`: latest simulation result
- `parameter_mapping`: reference mapping for a broader parameter set

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

From the project root:

```powershell
.\.venv\Scripts\python agent.py
```

You will be prompted with:

```text
Ask for simulation inputs:
```

Example prompts:

- `Set both stores to 6 seconds`
- `Make store 1 take 45 seconds and keep the other unchanged`
- `Change store 2 to 30`

## Runtime Flow

### 1. Input interpretation

`agent.py` uses an OpenAI agent with a structured `PlantInputs` schema to extract integer values for:

- `Store1ProcTime`
- `Store2ProcTime`

If the user only mentions one value, the agent is instructed to keep the other one unchanged.

### 2. Simulation launch

`model_handling._open_model()`:

- writes the updated parameters to `model_parameters.json`
- deletes any stale `model_results.json`
- launches `autoexecute_test.spp` with Plant Simulation

### 3. Result collection

`agent.py` waits up to 300 seconds for `model_results.json` to appear and contain valid JSON.

### 4. User-facing response

A second OpenAI agent reads the simulation results and returns a short explanation that includes `line_output`.

## Important Notes

- The current runtime code only uses `Store1ProcTime` and `Store2ProcTime`.
- The `parameter_mapping` file describes a larger set of possible model parameters, but it is not currently used by `agent.py` or `model_handling.py`.
- The two OpenAI agents in `agent.py` are both configured to use `gpt-5.4-mini`.
- The timeout for waiting on simulation results is currently 300 seconds.
- This project assumes the `.spp` model is configured to read `model_parameters.json` and write `model_results.json` during execution.

## Typical Use Case

This repository is useful as a lightweight prototype for:

- translating natural-language user requests into simulation inputs
- automating Plant Simulation launches from Python
- returning simulation outcomes in plain language
- experimenting with LLM-guided manufacturing or process simulation workflows

## Possible Next Improvements

- add a `requirements.txt` or `pyproject.toml`
- expose more simulation parameters through the structured schema
- validate user inputs before launching the model
- log simulation runs and results
- make the Plant Simulation executable path configurable
- add tests around JSON handling and timeout behavior
