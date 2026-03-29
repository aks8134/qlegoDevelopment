from utils import *
import pandas as pd
from qlego_generator import DefaultCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPipeline, QPassContext
import argparse
# Importing qiskit presets to use as "default for other stages"
from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetRoutingPass, PresetOptimizationPass, 
    PresetTranslationPass, PresetSchedulingPass
)
from qlego_qiskit.adapter.backend import QiskitBackend

def get_templates(sdk):
    # Load all passes from plugins
    aggregate_from_environment("envs/env_config.json")
    
    # Get all Layout passes from all plugins
    layout_passes = PassRegistry.get_passes_by_category("Layout")
    if sdk:
        layout_passes = {k: v for k, v in layout_passes.items() if sdk in k}
    templates = []
    
    for pass_key, pass_cls in list(layout_passes.items())[0:]:
        try:
            # Instantiate the Layout pass
            layout_instance = pass_cls()
            
            # Use Qiskit's preset passes for all other stages
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=layout_instance,
                routing=PresetRoutingPass(),
                optimization=PresetOptimizationPass(),
                translation=PresetTranslationPass(),
                # scheduling=PresetSchedulingPass() # Skip scheduling so it returns gates instead of pulses
            )
            t.name = pass_key
            templates.append(t)
        except Exception as e:
            print(f"Skipping layout pass {pass_key} due to initialization error: {e}")
            
    return templates

def run_mapping_experiments(sdk=None, no_save_results=False):
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    results = []
    templates = get_templates(sdk)
    print(f"Discovered {len(templates)} Layout templates: {[t.name for t in templates]}")
    
    for num_qubits in [5, 10]:
        for circuit_generator in [
            DJCircuitInitialization,
            GHZCircuitInitialization,
            GroverCircuitInitialization,
            QFTCircuitInitialization,
            AECircuitInitialization,
            QPECircuitInitialization,
            ShorCircuitInitialization,
            WStateCircuitInitialization,
            HalfAdderCircuitInitialization,
        ]:
            for template in templates:
                print(f"Running {template.name} for {circuit_generator.name} on {num_qubits} qubits...")
                result = {}
                result["mapping_strategy"] = template.name
                result["circuit_type"] = circuit_generator.name
                result["num_qubits"] = num_qubits
                result["error"] = ""
                try:
                    # Setup context with initial circuit and hardware
                    initial_qasm = initialize_circuit(circuit_generator, num_qubits)
                    ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
                    
                    # Compile using the template
                    compiled_ctx = template.compile(ctx=ctx)
                    
                    # Evaluate
                    metrics = evaluation_metrics(compiled_ctx.qasm)
                    
                    result["status"] = "success"
                    result = { **result, **metrics }
                    results.append(result)
                except Exception as e:
                    full_error = str(e)
                    try:
                        matches = [line.strip() for line in full_error.splitlines() if "Error:" in line or "Exception:" in line]
                        error_message_only = matches[-1] if matches else full_error.strip().splitlines()[-3]
                    except IndexError:
                        error_message_only = full_error[:200]
                    print(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}):\n{full_error}")
                    result["status"] = "failed"
                    result["error"] = error_message_only
                    results.append(result)
                
    df = pd.DataFrame(results)
    print(df)
    if not no_save_results:
        df.to_csv(f"mapping_experiment_results_{sdk}.csv", index=False)
        print(f"Saved mapping_experiment_results_{sdk}.csv")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=str, default=None)
    parser.add_argument("--no_save_results", action="store_true")
    args = parser.parse_args()
    run_mapping_experiments(args.sdk, args.no_save_results)
