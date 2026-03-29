"""
Experiment 1C: Optimization Pass Domain Specialization (H1)
===========================================================
Evaluates all individual optimization passes across circuit families
at multiple qubit scales on BOTH topologies (heavy-hex and all-to-all).

Layout, routing, translation fixed to Qiskit presets.
All-to-all topology isolates optimizer quality from routing artifacts.

Hypothesis H1: The optimal optimization pass depends on circuit structure.
"""

import argparse
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    STANDARD_QUBITS,
    initialize_circuit,
    get_heavy_hex_backend,
    get_all_to_all_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)


def get_optimization_templates(sdk=None):
    """Build templates for all registered optimization passes (standalone)."""
    ensure_registry()
    opt_passes = PassRegistry.get_passes_by_category("Optimization")

    if sdk:
        opt_passes = {k: v for k, v in opt_passes.items() if sdk in k}

    templates = []

    # Individual pass templates
    for pass_key, pass_cls in opt_passes.items():
        try:
            opt_inst = pass_cls()
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=PresetLayoutPass(),
                routing=PresetRoutingPass(),
                optimization=opt_inst,
                translation=PresetTranslationPass(),
            )
            t.name = pass_key
            t.opt_mode = "Standalone"
            templates.append(t)
        except Exception:
            pass

    # Baseline: no optimization
    t_base = DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        optimization=[],
        translation=PresetTranslationPass(),
    )
    t_base.name = "Baseline (No Optimization)"
    t_base.opt_mode = "Baseline"
    templates.append(t_base)

    return templates


def run(args):
    _, heavy_hex_json = get_heavy_hex_backend()
    templates = get_optimization_templates(args.sdk)
    print(f"Optimization configs: {len(templates)}")

    qubit_scales = args.qubits or STANDARD_QUBITS
    topologies = [("heavy_hex", heavy_hex_json)]
    if not args.heavy_hex_only:
        topologies.append(("all_to_all", None))  # backend_json built per qubit count

    results = []

    for topo_name, topo_json in topologies:
        total = len(qubit_scales) * len(ALL_CIRCUITS) * len(templates)
        pbar = tqdm(total=total, desc=f"Exp 1C: Optim ({topo_name})")

        for num_qubits in qubit_scales:
            backend_json = topo_json
            if topo_name == "all_to_all":
                backend_json = get_all_to_all_backend(num_qubits)

            for circuit_cls in ALL_CIRCUITS:
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
                            "optimization_pass": template.name,
                            "opt_mode": getattr(template, "opt_mode", ""),
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                            "topology": topo_name,
                        },
                    )
                    results.append(result)
                    pbar.update(1)

        pbar.close()

    df = pd.DataFrame(results)

    # Print top passes per circuit on heavy-hex
    success_hh = df[(df["status"] == "success") & (df["topology"] == "heavy_hex")]
    if not success_hh.empty:
        baseline = success_hh[success_hh["opt_mode"] == "Baseline"]
        standalone = success_hh[success_hh["opt_mode"] == "Standalone"]
        if not standalone.empty:
            print("\nBest optimization pass per circuit (heavy-hex):")
            print(standalone.groupby(["circuit_type", "num_qubits"]).apply(
                lambda g: g.loc[g["Circuit Depth"].idxmin(), "optimization_pass"]
            ).to_string())

    if not args.no_save:
        suffix = f"_{args.sdk}" if args.sdk else ""
        save_results(df, f"exp1_optimization{suffix}.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 1C: Optimization Specialization")
    parser.add_argument("--sdk", type=str, default=None)
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--heavy_hex_only", action="store_true", help="Skip all-to-all topology")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
