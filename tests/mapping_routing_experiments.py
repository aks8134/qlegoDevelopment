from utils import *
import pandas as pd
from qlego_generator import DefaultCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPassContext

# Importing qiskit presets to use as "default for other stages"
from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetOptimizationPass, PresetTranslationPass
)
from qlego_qiskit.adapter.backend import QiskitBackend

def get_templates():
    # Load all passes from plugins
    aggregate_from_environment("envs/env_config.json")
    
    # Get all Layout and Routing passes from all plugins
    layout_passes = PassRegistry.get_passes_by_category("Layout")
    routing_passes = PassRegistry.get_passes_by_category("Routing")
    templates = []
    
    for l_key, l_cls in list(layout_passes.items()):
        for r_key, r_cls in list(routing_passes.items()):
            try:
                # Instantiate the passes
                l_inst = l_cls()
                r_inst = r_cls()
                
                # Use Qiskit's preset passes for all other stages
                t = DefaultCompilationTemplate(
                    initialization=PresetInitPass(),
                    layout=l_inst,
                    routing=r_inst,
                    optimization=PresetOptimizationPass(),
                    translation=PresetTranslationPass(),
                )
                t.name = f"{l_key} + {r_key}"
                t.mapping_strategy = l_key
                t.routing_strategy = r_key
                templates.append(t)
            except Exception as e:
                print(f"Skipping combination {l_key} + {r_key} due to initialization error: {e}")
            
    return templates

def run_mapping_routing_experiments():
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    results = []
    templates = get_templates()
    print(f"Discovered {len(templates)} Combinatorial templates!")
    
    from tqdm import tqdm
    for num_qubits in [5, 10]:
        for circuit_generator in [
            DJCircuitInitialization,
            GHZCircuitInitialization
        ]:
            desc_str = f"{circuit_generator.name} ({num_qubits}q)"
            for template in tqdm(templates, desc=desc_str, unit="pass", leave=False):
                # print(f"Running {template.name} for {circuit_generator.name} on {num_qubits} qubits...")
                result = {}
                
                try:
                    # Setup context with initial circuit and hardware
                    initial_qasm = initialize_circuit(circuit_generator, num_qubits)
                    ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
                    
                    # Compile using the template
                    compiled_ctx = template.compile(ctx=ctx)
                    
                    # Evaluate
                    metrics = evaluation_metrics(compiled_ctx.qasm)
                    
                    result["mapping_strategy"] = template.mapping_strategy
                    result["routing_strategy"] = template.routing_strategy
                    result["circuit_type"] = circuit_generator.name
                    result["num_qubits"] = num_qubits
                    result = { **result, **metrics }
                    results.append(result)
                except Exception as e:
                    # Let the subprocess log handle it natively if desired, but keep the progress bar clean
                    tqdm.write(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}): {e}")
                
    df = pd.DataFrame(results)
    print(df)
    df.to_csv("mapping_routing_experiment_results.csv", index=False)
    print("Saved mapping_routing_experiment_results.csv")

if __name__ == "__main__":
    run_mapping_routing_experiments()
