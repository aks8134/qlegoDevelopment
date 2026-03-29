"""
Experiment 1B: Routing Pass Domain Specialization (H1)
======================================================
Evaluates all routing passes across all 9 circuit families at multiple
qubit scales on the heavy-hex topology.

Layout fixed to Qiskit SabreLayout, other stages to Qiskit presets.

Hypothesis H1: The optimal routing pass depends on circuit structure.
"""

import argparse
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    STANDARD_QUBITS,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    PresetInitPass,
    PresetLayoutPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)
from qlego_qiskit.adapter.passes import SabreLayoutPass


def get_routing_templates(sdk=None):
    """Build templates for all registered routing passes."""
    ensure_registry()
    routing_passes = PassRegistry.get_passes_by_category("Routing")

    if sdk:
        routing_passes = {k: v for k, v in routing_passes.items() if sdk in k}

    templates = []
    for pass_key, pass_cls in routing_passes.items():
        try:
            routing_instance = pass_cls()
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=SabreLayoutPass(),  # Fixed neutral layout
                routing=routing_instance,
                optimization=[],  # No optimization — isolate routing effect
                translation=PresetTranslationPass(),
            )
            t.name = pass_key
            templates.append(t)
        except Exception as e:
            print(f"Skipping {pass_key}: {e}")

    return templates


def run(args):
    _, backend_json = get_heavy_hex_backend()
    templates = get_routing_templates(args.sdk)
    print(f"Routing passes: {len(templates)} — {[t.name for t in templates]}")

    qubit_scales = args.qubits or STANDARD_QUBITS
    results = []

    total = len(qubit_scales) * len(ALL_CIRCUITS) * len(templates)
    pbar = tqdm(total=total, desc="Exp 1B: Routing")

    for num_qubits in qubit_scales:
        for circuit_cls in ALL_CIRCUITS:
            initial_qasm = None
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
            except Exception as e:
                print(f"Cannot generate {circuit_cls.name} at {num_qubits}q: {e}")
                pbar.update(len(templates))
                continue

            for template in templates:
                pbar.set_postfix_str(
                    f"{circuit_cls.name} {num_qubits}q {template.name}"
                )
                result = safe_run_pipeline(
                    template,
                    initial_qasm,
                    backend_json,
                    extra_result={
                        "routing_pass": template.name,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                        "topology": "heavy_hex",
                    },
                )
                results.append(result)
                pbar.update(1)

    pbar.close()
    df = pd.DataFrame(results)

    # Print best per circuit
    success = df[df["status"] == "success"]
    if not success.empty:
        print("\nBest routing pass per circuit:")
        print(success.groupby(["circuit_type", "num_qubits"]).apply(
            lambda g: g.loc[g["Circuit Depth"].idxmin(), "routing_pass"]
        ).to_string())

    if not args.no_save:
        suffix = f"_{args.sdk}" if args.sdk else ""
        save_results(df, f"exp1_routing{suffix}.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 1B: Routing Specialization")
    parser.add_argument("--sdk", type=str, default=None)
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
