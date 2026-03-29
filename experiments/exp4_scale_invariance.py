"""
Experiment 4: Scale Invariance of Optimal Pipeline (H4)
=======================================================
Tests whether the optimal pass ordering for a given circuit structure,
discovered at small qubit counts, remains near-optimal at larger scales.

Protocol:
  1. Run full layout x routing sweep at n=5 (cheap exhaustive search)
  2. Identify top-K pipelines per circuit family
  3. Run those exact pipelines at n = {10, 15, 20, 25, 30}
  4. Also run full sweep at n=20 to find true optimum
  5. Compute Spearman rank correlation and optimality gap

Hypothesis H4: For structurally regular circuits, the optimal pass
ordering transfers across qubit scales.
"""

import argparse
import pandas as pd
import numpy as np
from tqdm import tqdm
from scipy.stats import spearmanr

from common import (
    ALL_CIRCUITS,
    SCALE_QUBITS,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    PresetInitPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)


TOP_K = 5  # Number of top pipelines to track

# Circuit subset for scale invariance (structurally diverse)
SCALE_CIRCUITS = [
    c for c in ALL_CIRCUITS
    if c.name in ["GHZ Circuit", "DJ Circuit", "W State Circuit",
                   "QFT Circuit", "Grover Circuit"]
]


def get_layout_routing_templates():
    """Build all layout x routing combinations."""
    ensure_registry()
    layout_passes = PassRegistry.get_passes_by_category("Layout")
    routing_passes = PassRegistry.get_passes_by_category("Routing")

    templates = []
    for layout_key, layout_cls in layout_passes.items():
        for routing_key, routing_cls in routing_passes.items():
            try:
                t = DefaultCompilationTemplate(
                    initialization=PresetInitPass(),
                    layout=layout_cls(),
                    routing=routing_cls(),
                    optimization=[],
                    translation=PresetTranslationPass(),
                )
                t.name = f"{layout_key} + {routing_key}"
                t.layout_key = layout_key
                t.routing_key = routing_key
                templates.append(t)
            except Exception:
                pass

    return templates


def run(args):
    _, backend_json = get_heavy_hex_backend()
    all_templates = get_layout_routing_templates()
    print(f"Total layout x routing combos: {len(all_templates)}")

    qubit_scales = args.qubits or SCALE_QUBITS
    search_scale = qubit_scales[0]  # Find top-K at smallest scale
    verify_scale = 20 if 20 in qubit_scales else qubit_scales[-1]

    results = []

    # ---------------------------------------------------------------
    # Phase 1: Exhaustive search at smallest scale
    # ---------------------------------------------------------------
    print(f"\n--- Phase 1: Exhaustive search at n={search_scale} ---")

    phase1_results = {}  # {circuit_name: [(pipeline_name, depth), ...]}

    for circuit_cls in SCALE_CIRCUITS:
        try:
            initial_qasm = initialize_circuit(circuit_cls, search_scale)
        except Exception as e:
            print(f"Cannot generate {circuit_cls.name} at {search_scale}q: {e}")
            continue

        circuit_results = []
        for template in tqdm(all_templates, desc=f"{circuit_cls.name} ({search_scale}q)"):
            result = safe_run_pipeline(
                template,
                initial_qasm,
                backend_json,
                extra_result={
                    "pipeline": template.name,
                    "circuit_type": circuit_cls.name,
                    "num_qubits": search_scale,
                    "phase": "exhaustive_search",
                },
            )
            results.append(result)
            if result["status"] == "success":
                circuit_results.append((template.name, result.get("Circuit Depth", float("inf"))))

        # Sort and keep top-K
        circuit_results.sort(key=lambda x: x[1])
        phase1_results[circuit_cls.name] = circuit_results[:TOP_K]
        if circuit_results:
            print(f"  {circuit_cls.name}: top-{TOP_K} = {circuit_results[:TOP_K]}")

    # ---------------------------------------------------------------
    # Phase 2: Run top-K at all larger scales
    # ---------------------------------------------------------------
    print(f"\n--- Phase 2: Transfer top-{TOP_K} to larger scales ---")

    # Build name -> template lookup
    template_lookup = {t.name: t for t in all_templates}

    for circuit_cls in SCALE_CIRCUITS:
        top_pipelines = phase1_results.get(circuit_cls.name, [])
        if not top_pipelines:
            continue

        for num_qubits in qubit_scales:
            if num_qubits == search_scale:
                continue  # Already done

            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
            except Exception as e:
                print(f"Cannot generate {circuit_cls.name} at {num_qubits}q: {e}")
                continue

            for pipeline_name, _ in top_pipelines:
                template = template_lookup.get(pipeline_name)
                if template is None:
                    continue

                result = safe_run_pipeline(
                    template,
                    initial_qasm,
                    backend_json,
                    extra_result={
                        "pipeline": template.name,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                        "phase": "transfer",
                    },
                )
                results.append(result)

    # ---------------------------------------------------------------
    # Phase 3: Full sweep at verify_scale for ground truth
    # ---------------------------------------------------------------
    print(f"\n--- Phase 3: Full sweep at n={verify_scale} for ground truth ---")

    for circuit_cls in SCALE_CIRCUITS:
        try:
            initial_qasm = initialize_circuit(circuit_cls, verify_scale)
        except Exception as e:
            print(f"Cannot generate {circuit_cls.name} at {verify_scale}q: {e}")
            continue

        for template in tqdm(all_templates, desc=f"{circuit_cls.name} ({verify_scale}q)"):
            result = safe_run_pipeline(
                template,
                initial_qasm,
                backend_json,
                extra_result={
                    "pipeline": template.name,
                    "circuit_type": circuit_cls.name,
                    "num_qubits": verify_scale,
                    "phase": "verify_sweep",
                },
            )
            results.append(result)

    # ---------------------------------------------------------------
    # Analysis: Spearman correlation and optimality gap
    # ---------------------------------------------------------------
    df = pd.DataFrame(results)

    success = df[df["status"] == "success"]
    if not success.empty:
        print("\n--- Scale Invariance Analysis ---")

        for circuit_cls in SCALE_CIRCUITS:
            cname = circuit_cls.name
            small = success[
                (success["circuit_type"] == cname)
                & (success["num_qubits"] == search_scale)
            ].set_index("pipeline")["Circuit Depth"]

            large = success[
                (success["circuit_type"] == cname)
                & (success["num_qubits"] == verify_scale)
            ].set_index("pipeline")["Circuit Depth"]

            common = small.index.intersection(large.index)
            if len(common) >= 3:
                rho, pval = spearmanr(
                    small.loc[common].values,
                    large.loc[common].values,
                )
                # Optimality gap
                top_at_small = phase1_results.get(cname, [])
                if top_at_small:
                    best_small_name = top_at_small[0][0]
                    best_small_at_large = large.get(best_small_name)
                    best_at_large = large.min()
                    if best_small_at_large and best_at_large and best_at_large > 0:
                        gap = 100.0 * (best_small_at_large - best_at_large) / best_at_large
                    else:
                        gap = None
                else:
                    gap = None

                print(f"  {cname}: Spearman rho={rho:.3f} (p={pval:.3f}), "
                      f"gap={gap:.1f}%" if gap is not None else f"  {cname}: Spearman rho={rho:.3f}")

    if not args.no_save:
        save_results(df, "exp4_scale_invariance.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 4: Scale Invariance")
    parser.add_argument("--qubits", type=int, nargs="+", default=None,
                        help="Qubit scales (default: 5 10 15 20 25 30)")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
