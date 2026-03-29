from utils import *
import pandas as pd
from itertools import combinations
from qlego_generator import DefaultCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPassContext, QPipeline
import argparse
# Importing qiskit presets to use as "default for other stages"
from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetLayoutPass, PresetRoutingPass, PresetTranslationPass
)
from qlego_qiskit.adapter.backend import QiskitBackend
from tqdm import tqdm

def get_optimization_templates(sdk=None):
    aggregate_from_environment("envs/env_config.json")
    opt_passes = PassRegistry.get_passes_by_category("Optimization")
    templates = []
    if(sdk):
        opt_passes = {k: v for k, v in opt_passes.items() if sdk in k}
        print(opt_passes.keys())
    # ---------------------------------------------------------
    # PART 1: STANDALONE EVALUATION (Isolated Pass Performance)
    # ---------------------------------------------------------
    for pass_key, pass_cls in list(opt_passes.items()):
        try:
            opt_inst = pass_cls()
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=PresetLayoutPass(),
                routing=PresetRoutingPass(),
                optimization=opt_inst, # Single pass isolated
                translation=PresetTranslationPass(),
            )
            t.name = f"Standalone: {pass_key}"
            t.opt_mode = "Standalone"
            t.opt_sequence = pass_key
            templates.append(t)
        except Exception as e:
            pass # Skip initialization failures cleanly
            
    # ---------------------------------------------------------
    # PART 2: SDK-SPECIFIC CHAIN EVALUATION
    # Combine optimization passes belonging to the same SDK 
    # to form standard heuristic reduction chains
    # ---------------------------------------------------------
    if( sdk == None ):
        sdk_groups = {"qiskit": [], "tket": [], "bqskit": [], "cirq": []}
        for key, cls in opt_passes.items():
            if "qiskit" in key: sdk_groups["qiskit"].append((key, cls))
            elif "tket" in key: sdk_groups["tket"].append((key, cls))
            elif "bqskit" in key: sdk_groups["bqskit"].append((key, cls))
            elif "cirq" in key: sdk_groups["cirq"].append((key, cls))
            
        for sdk, group in sdk_groups.items():
            if not group: continue
            try:
                # Instantiate all passes in the group as a sequential list
                # Note: order matters in optimization, but iterating their native registration is a good baseline
                instances = [cls() for name, cls in group]
                
                t = DefaultCompilationTemplate(
                    initialization=PresetInitPass(),
                    layout=PresetLayoutPass(),
                    routing=PresetRoutingPass(),
                    optimization=instances, # List of sequential SDK passes
                    translation=PresetTranslationPass(),
                )
                t.name = f"Full-SDK-Chain: {sdk.upper()}"
                t.opt_mode = "Full SDK Chain"
                t.opt_sequence = " -> ".join([name for name, cls in group])
                templates.append(t)
            except Exception as e:
                pass
                
        # Add an Empty baseline!
        t_base = DefaultCompilationTemplate(
            initialization=PresetInitPass(),
            layout=PresetLayoutPass(),
            routing=PresetRoutingPass(),
            optimization=[], # NO OPTIMIZATION
            translation=PresetTranslationPass(),
        )
        t_base.name = "Baseline (No Optimization)"
        t_base.opt_mode = "Baseline"
        t_base.opt_sequence = "None"
        templates.append(t_base)
            
    return templates

def run_optimization_experiments(args):
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    
    results = []
    templates = get_optimization_templates(args.sdk)
    print(f"Discovered {len(templates)} Optimization configurations!")
    
    for num_qubits in [5, 10]:
        for circuit_generator in [
            DJCircuitInitialization,
            GHZCircuitInitialization
        ]:
            desc_str = f"{circuit_generator.name} ({num_qubits}q)"
            for template in tqdm(templates, desc=desc_str, unit="pass", leave=False):
                result = {}
                result["opt_category"] = template.opt_mode
                result["opt_sequence"] = template.opt_sequence
                result["circuit_type"] = circuit_generator.name
                result["num_qubits"] = num_qubits
                result["error"] = ""
                try:
                    initial_qasm = initialize_circuit(circuit_generator, num_qubits)
                    ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
                    
                    compiled_ctx = template.compile(ctx=ctx)
                    metrics = evaluation_metrics(compiled_ctx.qasm)
                    
                    result["status"] = "success"
                    result = { **result, **metrics }
                    results.append(result)
                except Exception as e:
                    tqdm.write(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}): {e}")
                    full_error = str(e)
                    error_message_only = full_error.strip().splitlines()[-3]
                    result["status"] = "failed"
                    result["error"] = error_message_only
                    results.append(result)
    df = pd.DataFrame(results)
    
    # Optional: Calculate improvement over Baseline
    print(df)
    if not args.no_save_results:
        df.to_csv("optimization_experiment_results.csv", index=False)
        print("Saved optimization_experiment_results.csv")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk", type=str, default=None)
    parser.add_argument("--no_save_results", action="store_true", default = False)
    args = parser.parse_args()
    run_optimization_experiments(args)
