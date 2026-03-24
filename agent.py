# basic_agent_json_edit_existing.py

import asyncio
import json
from pathlib import Path
from pydantic import BaseModel, Field
from agents import Agent, Runner
from dotenv import load_dotenv
import os

from model_handling import RESULTS_PATH, _open_model


load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
print(api_key is not None)


BASE_DIR = Path(__file__).resolve().parent
JSON_FILE = BASE_DIR / "plant_inputs.json"
SIMULATION_TIMEOUT_SECONDS = 300

class PlantInputs(BaseModel):
    Store1ProcTime: int = Field(description="Processing time for store 1 in seconds")
    Store2ProcTime: int = Field(description="Processing time for store 2 in seconds")


agent = Agent(
    name="Plant Simulation Input Agent",
    instructions=(
        "You are a helper for Siemens Plant Simulation. "
        "Read the user's request and return updated integer values for "
        "Store1ProcTime and Store2ProcTime only. "
        "If the user mentions only one variable, keep the other at its existing/default value."
    ),
    output_type=PlantInputs,
    model="gpt-5.4-mini",
)
response_agent = Agent(
    name="Plant Simulation Response Agent",
    instructions=(
        "You explain Plant Simulation results to the user. "
        "Use the simulation results provided. "
        "Reply briefly and clearly. Mention the value of line_output."
    ),
    model="gpt-5.4-mini",
)

def load_existing_json(filepath: Path) -> dict:
    if filepath.exists():
        return json.loads(filepath.read_text(encoding="utf-8"))
    return {
        "Store1ProcTime": 60,
        "Store2ProcTime": 60
    }


def save_json(filepath: Path, data: dict) -> None:
    filepath.write_text(json.dumps(data, indent=4), encoding="utf-8")

async def wait_for_simulation_results(timeout_seconds: int) -> dict | None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds

    while asyncio.get_running_loop().time() < deadline:
        if RESULTS_PATH.is_file():
            try:
                return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

        await asyncio.sleep(0.5)

    return None

async def main() -> str:
    current_data = load_existing_json(JSON_FILE)
    user_prompt = input("Ask for simulation inputs: ")

    edit_prompt = (
        f"Current JSON values are:\n{json.dumps(current_data, indent=4)}\n\n"
        f"User request:\n{user_prompt}"
    )

    print("Calling Agent")
    edit_result = await Runner.run(agent, edit_prompt)
    updated = edit_result.final_output.model_dump()
    print("Updating Json")
    save_json(JSON_FILE, updated)

    print("Opening Model")
    _open_model(updated)


    results = await wait_for_simulation_results(SIMULATION_TIMEOUT_SECONDS)
    if results is None:
        return "The simulation did not return results."
    
    response_prompt = (
        f"User request:\n{user_prompt}\n\n"
        f"Updated inputs:\n{json.dumps(updated, indent=4)}\n\n"
        f"Simulation results:\n{json.dumps(results, indent=4)}\n\n"
        "Reply to the user in one short sentence. Mention the line_output."
    )

    response_result = await Runner.run(response_agent, response_prompt)
    return response_result.final_output


if __name__ == "__main__":
    print(asyncio.run(main()))
