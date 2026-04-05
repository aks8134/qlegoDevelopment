"""
Experiment 4: Scale Invariance of Optimal Pipeline (H4)
=======================================================
Tests whether the optimal pass ordering for a given circuit structure,
discovered at small qubit counts, remains near-optimal at larger scales.

Two sub-experiments:
  H4a — Mapping scale invariance (layout x routing):
    1. Run full layout x routing sweep at n=5 (exhaustive search)
    2. Identify top-K pipelines per circuit family
    3. Run those exact pipelines at n = {10, 15, 20, 25, 30}
    4. Also run full sweep at n=20 for ground truth
    5. Compute Spearman rank correlation and optimality gap

  H4b — Optimization scale invariance:
    1. Load top-5 optimization pipelines per circuit from exp1_optimization.csv
    2. Run those pipelines at all qubit scales
    3. Compute Spearman rank correlation and optimality gap vs best at each scale

Hypothesis H4: For structurally regular circuits, the optimal pass
ordering transfers across qubit scales.
"""

import argparse
import os
import pandas as pd
import numpy as np
from tqdm import tqdm
from scipy.stats import spearmanr

from common import (
    ALL_CIRCUITS,
    SCALE_QUBITS,
    RESULTS_DIR,
    get_qubits_for_circuit,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    flush_results,
    QPassContext,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)
from qlego_generator.bundled_template import RoleBasedCompilationTemplate, BUNDLE_STAGES


TOP_K = 5  # Number of top pipelines to track

# Circuit subset for scale invariance (structurally diverse)
SCALE_CIRCUITS = [
    c for c in ALL_CIRCUITS
    if c.name in ["GHZ Circuit", "DJ Circuit", "W State Circuit",
                   "QFT Circuit", "Grover Circuit"]
]


def get_layout_routing_templates():
    """Build all layout x routing combinations (Cirq excluded)."""
    ensure_registry()
    layout_passes = {
        k: v for k, v in PassRegistry.get_passes_by_category("Layout").items()
        if "cirq" not in k.lower()
    }
    routing_passes = {
        k: v for k, v in PassRegistry.get_passes_by_category("Routing").items()
        if "cirq" not in k.lower()
    }

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


# ---------------------------------------------------------------------------
# H4b helpers: load top optimization pipelines from exp1 results
# ---------------------------------------------------------------------------

def load_top_opt_pipelines(top_k=TOP_K, qubit_scale=5):
    """
    Load the top-K optimization pipelines per circuit from exp1_optimization.csv.
    Returns {circuit_name: [(opt_sequence, depth), ...]} sorted best-first.
    """
    csv_path = os.path.join(RESULTS_DIR, "exp1_optimization.csv")
    if not os.path.exists(csv_path):
        print(f"  exp1_optimization.csv not found at {csv_path}. Skipping H4b.")
        return {}

    df = pd.read_csv(csv_path)
    df = df[
        (df["status"] == "success") &
        (df["num_qubits"] == qubit_scale) &
        (df["Circuit Depth"].notna())
    ]

    top_per_circuit = {}
    for cname, group in df.groupby("circuit_type"):
        ranked = (
            group.groupby("opt_sequence")["Circuit Depth"]
            .min()
            .sort_values()
            .head(top_k)
        )
        top_per_circuit[cname] = list(zip(ranked.index, ranked.values))

    return top_per_circuit


def rebuild_opt_template(opt_sequence: str, passes_per_stage: dict):
    """
    Reconstruct a RoleBasedCompilationTemplate from a stored opt_sequence string
    (format: "pass_key1 -> pass_key2 -> ...").
    """
    keys = [k.strip() for k in opt_sequence.split("->") if k.strip() and k.strip() != "none"]
    bundle_map = {}
    for key in keys:
        for stage, stage_passes in passes_per_stage.items():
            if key in stage_passes:
                bundle_map[stage] = (key, stage_passes[key])
                break

    instantiated = {}
    for stage, (key, cls) in bundle_map.items():
        try:
            instantiated[stage] = cls()
        except Exception:
            pass

    t = RoleBasedCompilationTemplate(
        name=f"H4b: {opt_sequence[:60]}",
        bundle_passes=instantiated,
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        translation=PresetTranslationPass(),
    )
    t.opt_sequence = opt_sequence
    return t


def get_all_passes_per_stage():
    """Return {stage: {pass_key: pass_cls}} excluding Cirq."""
    ensure_registry()
    return {
        stage: {
            k: v for k, v in PassRegistry.get_passes_by_category(stage).items()
            if "cirq" not in k.lower()
        }
        for stage in BUNDLE_STAGES
    }


def run(args):
    _, backend_json = get_heavy_hex_backend()
    all_templates = get_layout_routing_templates()
    print(f"Total layout x routing combos (no Cirq): {len(all_templates)}")

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

    if not args.no_save:
        flush_results(results, "exp4_scale_invariance.csv")

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

    if not args.no_save:
        flush_results(results, "exp4_scale_invariance.csv")

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

    if not args.no_save:
        flush_results(results, "exp4_scale_invariance.csv")

    # ---------------------------------------------------------------
    # Phase 4 (H4b): Optimization scale invariance
    # ---------------------------------------------------------------
    print(f"\n--- Phase 4 (H4b): Optimization scale invariance ---")

    passes_per_stage = get_all_passes_per_stage()
    top_opt_pipelines = load_top_opt_pipelines(top_k=TOP_K, qubit_scale=search_scale)

    h4b_phase1 = {}  # {circuit_name: [(opt_sequence, depth), ...]}

    if not top_opt_pipelines:
        print("  No exp1_optimization.csv found — skipping H4b.")
    else:
        for circuit_cls in SCALE_CIRCUITS:
            cname = circuit_cls.name
            top_pipelines = top_opt_pipelines.get(cname, [])
            if not top_pipelines:
                print(f"  No top pipelines found for {cname} — skipping.")
                continue

            h4b_phase1[cname] = top_pipelines
            print(f"  {cname}: top-{TOP_K} opt pipelines = {[s for s, _ in top_pipelines]}")

            for num_qubits in qubit_scales:
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                except Exception as e:
                    print(f"Cannot generate {cname} at {num_qubits}q: {e}")
                    continue

                for opt_sequence, _ in top_pipelines:
                    try:
                        template = rebuild_opt_template(opt_sequence, passes_per_stage)
                    except Exception as e:
                        print(f"  Cannot rebuild template for '{opt_sequence}': {e}")
                        continue

                    result = safe_run_pipeline(
                        template,
                        initial_qasm,
                        backend_json,
                        extra_result={
                            "pipeline": template.name,
                            "opt_sequence": opt_sequence,
                            "circuit_type": cname,
                            "num_qubits": num_qubits,
                            "phase": "h4b_opt_transfer",
                        },
                    )
                    results.append(result)

    if not args.no_save:
        flush_results(results, "exp4_scale_invariance.csv")

    # ---------------------------------------------------------------
    # Analysis: Spearman correlation and optimality gap
    # ---------------------------------------------------------------
    df = pd.DataFrame(results)

    success = df[df["status"] == "success"]
    if not success.empty:
        print("\n--- H4a: Mapping Scale Invariance Analysis ---")

        for circuit_cls in SCALE_CIRCUITS:
            cname = circuit_cls.name
            small = success[
                (success["circuit_type"] == cname)
                & (success["num_qubits"] == search_scale)
                & (success["phase"].isin(["exhaustive_search", "verify_sweep"]))
            ].set_index("pipeline")["Circuit Depth"]

            large = success[
                (success["circuit_type"] == cname)
                & (success["num_qubits"] == verify_scale)
                & (success["phase"] == "verify_sweep")
            ].set_index("pipeline")["Circuit Depth"]

            common = small.index.intersection(large.index)
            if len(common) >= 3:
                rho, pval = spearmanr(
                    small.loc[common].values,
                    large.loc[common].values,
                )
                top_at_small = phase1_results.get(cname, [])
                if top_at_small:
                    best_small_name = top_at_small[0][0]
                    best_small_at_large = large.get(best_small_name)
                    best_at_large = large.min()
                    if best_small_at_large is not None and best_at_large and best_at_large > 0:
                        gap = 100.0 * (best_small_at_large - best_at_large) / best_at_large
                    else:
                        gap = None
                else:
                    gap = None

                if gap is not None:
                    print(f"  {cname}: Spearman rho={rho:.3f} (p={pval:.3f}), gap={gap:.1f}%")
                else:
                    print(f"  {cname}: Spearman rho={rho:.3f} (p={pval:.3f})")

        # H4b analysis
        if h4b_phase1:
            print("\n--- H4b: Optimization Scale Invariance Analysis ---")
            h4b_success = success[success["phase"] == "h4b_opt_transfer"]

            for circuit_cls in SCALE_CIRCUITS:
                cname = circuit_cls.name
                if cname not in h4b_phase1:
                    continue

                small_opt = h4b_success[
                    (h4b_success["circuit_type"] == cname)
                    & (h4b_success["num_qubits"] == search_scale)
                ].set_index("opt_sequence")["Circuit Depth"]

                large_opt = h4b_success[
                    (h4b_success["circuit_type"] == cname)
                    & (h4b_success["num_qubits"] == verify_scale)
                ].set_index("opt_sequence")["Circuit Depth"]

                common_opt = small_opt.index.intersection(large_opt.index)
                if len(common_opt) >= 3:
                    rho, pval = spearmanr(
                        small_opt.loc[common_opt].values,
                        large_opt.loc[common_opt].values,
                    )
                    # Optimality gap: best-at-small-scale vs best-at-large-scale
                    best_seq_at_small = h4b_phase1[cname][0][0]
                    best_at_large_opt = large_opt.min()
                    best_transferred = large_opt.get(best_seq_at_small)
                    if best_transferred is not None and best_at_large_opt and best_at_large_opt > 0:
                        gap = 100.0 * (best_transferred - best_at_large_opt) / best_at_large_opt
                        print(f"  {cname}: Spearman rho={rho:.3f} (p={pval:.3f}), gap={gap:.1f}%")
                    else:
                        print(f"  {cname}: Spearman rho={rho:.3f} (p={pval:.3f})")
                elif len(common_opt) > 0:
                    print(f"  {cname}: only {len(common_opt)} common pipelines — insufficient for correlation")

    if not args.no_save:
        save_results(df, "exp4_scale_invariance.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 4: Scale Invariance")
    parser.add_argument("--qubits", type=int, nargs="+", default=None,
                        help="Qubit scales (default: 5 10 15 20 25 30)")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
