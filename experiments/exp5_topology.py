"""
Experiment 5: Topology-Dependent Ordering (H1 + H3)
====================================================
Tests whether switching hardware topology changes the RANKING of optimal
pass orderings, not just which individual pass is best.

Protocol:
  1. Run optimization pass sweep on heavy-hex (from Exp 1C)
  2. Identify top-5 optimization passes per circuit on heavy-hex
  3. Run those same passes on all-to-all topology
  4. Compare rankings via Spearman correlation

If rankings differ, topology independently affects pass ORDERING,
not just pass SELECTION — a strictly stronger claim.

Also evaluates layout and routing passes on all-to-all for comparison.
"""

import argparse
import pandas as pd
import numpy as np
from tqdm import tqdm
from scipy.stats import spearmanr

from common import (
    ALL_CIRCUITS,
    initialize_circuit,
    evaluate,
    get_heavy_hex_backend,
    get_all_to_all_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    QPassContext,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)


def get_optimization_templates(sdk=None):
    """Build standalone optimization templates."""
    ensure_registry()
    opt_passes = PassRegistry.get_passes_by_category("Optimization")
    if sdk:
        opt_passes = {k: v for k, v in opt_passes.items() if sdk in k}

    templates = []
    for pass_key, pass_cls in opt_passes.items():
        try:
            t = DefaultCompilationTemplate(
                initialization=PresetInitPass(),
                layout=PresetLayoutPass(),
                routing=PresetRoutingPass(),
                optimization=pass_cls(),
                translation=PresetTranslationPass(),
            )
            t.name = pass_key
            templates.append(t)
        except Exception:
            pass

    # Baseline
    t_base = DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        optimization=[],
        translation=PresetTranslationPass(),
    )
    t_base.name = "Baseline"
    templates.append(t_base)

    return templates


def run(args):
    _, heavy_hex_json = get_heavy_hex_backend()
    templates = get_optimization_templates()
    print(f"Optimization passes: {len(templates)}")

    qubit_scales = args.qubits or [5, 10]
    results = []

    for topo_name in ["heavy_hex", "all_to_all"]:
        total = len(qubit_scales) * len(ALL_CIRCUITS) * len(templates)
        pbar = tqdm(total=total, desc=f"Exp 5: {topo_name}")

        for num_qubits in qubit_scales:
            if topo_name == "heavy_hex":
                backend_json = heavy_hex_json
            else:
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
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                            "topology": topo_name,
                        },
                    )
                    results.append(result)
                    pbar.update(1)

        pbar.close()

    df = pd.DataFrame(results)

    # Analysis: compare rankings between topologies
    success = df[df["status"] == "success"]
    if not success.empty:
        print("\n--- Topology Ranking Comparison ---")

        for circuit_cls in ALL_CIRCUITS:
            for nq in qubit_scales:
                hh = success[
                    (success["circuit_type"] == circuit_cls.name)
                    & (success["num_qubits"] == nq)
                    & (success["topology"] == "heavy_hex")
                ].set_index("optimization_pass")["Circuit Depth"]

                aa = success[
                    (success["circuit_type"] == circuit_cls.name)
                    & (success["num_qubits"] == nq)
                    & (success["topology"] == "all_to_all")
                ].set_index("optimization_pass")["Circuit Depth"]

                common = hh.index.intersection(aa.index)
                if len(common) >= 3:
                    rho, pval = spearmanr(
                        hh.loc[common].values,
                        aa.loc[common].values,
                    )
                    best_hh = hh.loc[common].idxmin()
                    best_aa = aa.loc[common].idxmin()
                    changed = "YES" if best_hh != best_aa else "no"
                    print(f"  {circuit_cls.name} ({nq}q): "
                          f"rho={rho:.3f}, best changes={changed} "
                          f"(HH:{best_hh}, A2A:{best_aa})")

    if not args.no_save:
        save_results(df, "exp5_topology.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 5: Topology Dependence")
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
