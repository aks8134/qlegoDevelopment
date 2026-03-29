from utils import *
import pandas as pd
from qlego_generator import DefaultCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPipeline, QPassContext
import argparse
from tqdm import tqdm

# Importing qiskit presets to use as "default for other stages"
from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetLayoutPass, PresetOptimizationPass, 
    PresetTranslationPass
)
from qlego_qiskit.adapter.backend import QiskitBackend

def get_templates(sdk):
    # Load all passes from plugins
    aggregate_from_environment("envs/env_config.json")
    
    # Get all Routing passes from all plugins
    routing_passes = PassRegistry.get_passes_by_category("Routing")
    if sdk:
        routing_passes = {k: v for k, v in routing_passes.items() if sdk in k}
    templates = []
    
    for pass_key, pass_cls in list(routing_passes.items())[0:]:
        try:
            # Instantiate the Routing pass
            routing_instance = pass_cls()
            
            # Use Qiskit's preset passes for all other stages
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=PresetLayoutPass(),
                routing=routing_instance,
                optimization=PresetOptimizationPass(),
                translation=PresetTranslationPass(),
            )
            t.name = pass_key
            templates.append(t)
        except Exception as e:
            print(f"Skipping routing pass {pass_key} due to initialization error: {e}")
            
    return templates

def run_routing_experiments(sdk=None, no_save_results=False):
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    results = []
    templates = get_templates(sdk)
    print(f"Discovered {len(templates)} Routing templates: {[t.name for t in templates]}")
    
    for num_qubits in [5, 10]:
        for circuit_generator in tqdm([
            DJCircuitInitialization,
            GHZCircuitInitialization,
            GroverCircuitInitialization,
            QFTCircuitInitialization,
            AECircuitInitialization,
            QPECircuitInitialization,
            ShorCircuitInitialization,
            WStateCircuitInitialization,
            HalfAdderCircuitInitialization,
        ]):
            for template in templates:
                print(f"Running {template.name} for {circuit_generator.name} on {num_qubits} qubits...")
                result = {}
                result["routing_strategy"] = template.name
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
                    print(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}): {e}")
                    full_error = str(e)
                    error_message_only = full_error.strip().splitlines()[-3]
                    result["status"] = "failed"
                    result["error"] = error_message_only
                    results.append(result)
                
    df = pd.DataFrame(results)
    print(df)
    if not no_save_results:
        df.to_csv(f"routing_experiment_results_{sdk}.csv", index=False)
        print(f"Saved routing_experiment_results_{sdk}.csv")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=str, default=None)
    parser.add_argument("--no_save_results", action="store_true")
    args = parser.parse_args()
    run_routing_experiments(args.sdk, args.no_save_results)
