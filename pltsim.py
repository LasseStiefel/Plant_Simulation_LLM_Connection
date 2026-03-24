import sys

sys.path.append(r"C:\Users\lasse\Syddansk Universitet\SDU CIFA & Others - General\Plant_Simulation_LLM_Connection")
from model_handling import _get_param, _send_sim_results

import PlantSimulation as ps

def initLLM():
    print("initLLM started")
    parameters = _get_param()
    print("parameter received. Applying variables.")  
    
    for route, value in parameters.items():
        exec(f"{route} = {repr(value)}", globals(), locals())
    print("variables applied")
    
def sendResults():
    # output results
    simulation_results = {
        "line_output": root.Drain.StatNumOut
    }
    
    # send dict
    _send_sim_results(simulation_results)