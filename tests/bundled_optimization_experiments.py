"""
Bundled Optimization Experiments
================================
Evaluates optimization pipelines where each stage itself is a specific ROLE.
Generates N random hybrid pipelines by picking exactly one pass for each 
bundle slot from the QLego PassRegistry.
"""

from utils import *
import pandas as pd
import random
from qlego_generator.template import DefaultCompilationTemplate
from qlego_generator.bundled_template import RoleBasedCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qlego.qpass import QPassContext
import argparse
import subprocess
import os

# Patch subprocess.run to enforce a 5-minute timeout for stuck passes
_original_run = subprocess.run
def _run_with_timeout(*args, **kwargs):
    kwargs.setdefault('timeout', 300)
    try:
        return _original_run(*args, **kwargs)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Timeout Error: Pipeline took longer than 5 minutes.") from e
subprocess.run = _run_with_timeout

from qlego_qiskit.adapter.passes import (
    PresetInitPass, PresetLayoutPass, PresetRoutingPass, PresetTranslationPass,
)
from qlego_qiskit.adapter.backend import QiskitBackend
from tqdm import tqdm


def get_randomized_hybrid_templates(num_random_hybrids=10):
    """Build N random cross-SDK hybrid pipelines from role-based bundles."""
    # Ensure all passes are registered
    env_cfg_path = os.path.join(os.path.dirname(__file__), "envs/env_config.json")
    aggregate_from_environment(env_cfg_path)
    
    templates = []
    bundle_categories = RoleBasedCompilationTemplate.get_bundle_categories()
    
    # Pre-fetch and instantiate all available passes per bundle category
    available_passes = {}
    for cat in bundle_categories:
        available_passes[cat] = []
        for pass_key, pass_cls in PassRegistry.get_passes_by_category(cat).items():
            try:
                available_passes[cat].append((pass_key, pass_cls()))
            except Exception:
                pass

    print(f"Generating {num_random_hybrids} random hybrid pipelines...")

    # Generate N random pipelines
    for i in range(num_random_hybrids):
        chosen_passes = {}
        chosen_keys = []
        
        for cat in bundle_categories:
            if not available_passes.get(cat):
                continue
            # randomly choose exactly one pass for this bundle slot
            pass_key, inst = random.choice(available_passes[cat])
            chosen_passes[cat] = inst
            chosen_keys.append(pass_key)
            
        if not chosen_passes:
            continue
            
        t = RoleBasedCompilationTemplate(
            name=f"Random-Hybrid-{i+1}",
            bundle_passes=chosen_passes,
            initialization=PresetInitPass(),
            layout=PresetLayoutPass(),
            routing=PresetRoutingPass(),
            translation=PresetTranslationPass()
        )
        t.opt_mode = "Random Hybrid Pipeline"
        t.opt_sequence = " → ".join(chosen_keys)
        templates.append(t)

    return templates


def run_bundled_experiments(args):
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()

    results = []
    templates = get_randomized_hybrid_templates(args.num_random_hybrids)

    for num_qubits in [5, 10]:
        for circuit_generator in [
            DJCircuitInitialization,
            GHZCircuitInitialization,
        ]:
            desc_str = f"{circuit_generator.name} ({num_qubits}q)"
            for template in tqdm(templates, desc=desc_str, unit="pipeline", leave=False):
                result = {}
                result["pipeline_name"] = template.name
                result["opt_category"] = getattr(template, "opt_mode", "")
                result["opt_sequence"] = getattr(template, "opt_sequence", "")
                result["circuit_type"] = circuit_generator.name
                result["num_qubits"] = num_qubits
                result["error"] = ""
                
                try:
                    initial_qasm = initialize_circuit(circuit_generator, num_qubits)
                    ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)

                    compiled_ctx = template.compile(ctx=ctx)
                    metrics = evaluation_metrics(compiled_ctx.qasm)

                    result["status"] = "success"
                    result = {**result, **metrics}
                    results.append(result)
                except RuntimeError as e:
                    full_error = str(e)
                    if "Timeout Error" in full_error:
                        tqdm.write(f"Timeout {template.name} for {circuit_generator.name} ({num_qubits}): > 5 mins")
                        result["status"] = "failed"
                        result["error"] = "Timeout error (> 5 mins)"
                    else:
                        try:
                            matches = [line.strip() for line in full_error.splitlines() if "Error:" in line or "Exception:" in line]
                            error_message_only = matches[-1] if matches else full_error.strip().splitlines()[-3]
                        except IndexError:
                            error_message_only = full_error[:200]
                        tqdm.write(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}): {error_message_only}")
                        result["status"] = "failed"
                        result["error"] = error_message_only
                    results.append(result)
                except Exception as e:
                    full_error = str(e)
                    try:
                        matches = [line.strip() for line in full_error.splitlines() if "Error:" in line or "Exception:" in line]
                        error_message_only = matches[-1] if matches else full_error.strip().splitlines()[-3]
                    except IndexError:
                        error_message_only = full_error[:200]
                    tqdm.write(f"Failed {template.name} for {circuit_generator.name} ({num_qubits}): {error_message_only}")
                    result["status"] = "failed"
                    result["error"] = error_message_only
                    results.append(result)

    df = pd.DataFrame(results)
    print(df)

    if not args.no_save_results:
        df.to_csv("bundled_optimization_experiment_results.csv", index=False)
        print("Saved bundled_optimization_experiment_results.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Role-based bundled optimization experiments")
    parser.add_argument("--num_random_hybrids", type=int, default=10,
                        help="Number of random cross-SDK hybrid pipelines to generate")
    parser.add_argument("--no_save_results", action="store_true", default=False)
    args = parser.parse_args()
    run_bundled_experiments(args)
