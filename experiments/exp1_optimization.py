"""
Experiment 1C: Optimization Pass Domain Specialization (H1)
===========================================================
Systematic 3-tier evaluation of optimization passes using the
RoleBasedCompilationTemplate (6 semantic bundle stages).

Tier 1 — Per-stage standalone:
    For each of the 6 bundle stages, test every registered pass in that
    stage individually (all other stages empty). Identifies the best
    pass per stage per circuit — the atomic H1 evidence for optimization.

Tier 2 — Same-SDK full chains:
    Run all passes from one SDK across all 6 bundle stages sequentially.
    Baseline (no optimization) included for reference.

Tier 3 — Cross-SDK best-of-stage combo:
    Take the best pass per stage from Tier 1 results (for each circuit)
    and combine them into a single cross-SDK pipeline. Compared against
    the best same-SDK chain from Tier 2.

Hypothesis H1: The optimal optimization pass depends on circuit structure;
no single SDK dominates across all circuit families.
"""

import argparse
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    STANDARD_QUBITS,
    get_qubits_for_circuit,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    QPassContext,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
)
from qlego_generator.bundled_template import RoleBasedCompilationTemplate, BUNDLE_STAGES


def get_passes_per_stage(exclude_sdks=("cirq",)):
    """
    Return dict: {stage: {pass_key: pass_cls}} for all bundle stages,
    excluding specified SDKs.
    """
    ensure_registry()
    result = {}
    for stage in BUNDLE_STAGES:
        passes = PassRegistry.get_passes_by_category(stage)
        result[stage] = {
            k: v for k, v in passes.items()
            if not any(sdk in k.lower() for sdk in exclude_sdks)
        }
    return result


def get_sdk_chains(passes_per_stage, sdks=("qiskit", "tket", "bqskit")):
    """
    For each SDK, collect the best available pass per bundle stage.
    Returns dict: {sdk: {stage: (pass_key, pass_cls)}}
    """
    chains = {}
    for sdk in sdks:
        chain = {}
        for stage, stage_passes in passes_per_stage.items():
            sdk_passes = {k: v for k, v in stage_passes.items() if sdk in k.lower()}
            if sdk_passes:
                # Take first registered pass for that SDK in this stage
                key, cls = next(iter(sdk_passes.items()))
                chain[stage] = (key, cls)
        if chain:
            chains[sdk] = chain
    return chains


def build_bundle_template(name, bundle_pass_map):
    """
    Build a RoleBasedCompilationTemplate from a {stage: (key, cls)} map.
    Stages not in bundle_pass_map are left empty.
    """
    instantiated = {}
    sequence_parts = []
    for stage in BUNDLE_STAGES:
        if stage in bundle_pass_map:
            key, cls = bundle_pass_map[stage]
            try:
                instantiated[stage] = cls()
                sequence_parts.append(key)
            except Exception:
                pass

    t = RoleBasedCompilationTemplate(
        name=name,
        bundle_passes=instantiated,
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        translation=PresetTranslationPass(),
    )
    t.opt_sequence = " -> ".join(sequence_parts) if sequence_parts else "none"
    return t


def run(args):
    _, backend_json = get_heavy_hex_backend()
    qubit_scales = args.qubits or STANDARD_QUBITS
    passes_per_stage = get_passes_per_stage()
    sdk_chains = get_sdk_chains(passes_per_stage)

    results = []

    # -----------------------------------------------------------------------
    # Tier 1: Per-stage standalone — test each pass in isolation per stage
    # -----------------------------------------------------------------------
    print("\n=== Tier 1: Per-stage standalone ===")
    for stage in BUNDLE_STAGES:
        stage_passes = passes_per_stage[stage]
        if not stage_passes:
            continue
        print(f"  {stage}: {len(stage_passes)} passes")

        for pass_key, pass_cls in stage_passes.items():
            try:
                bundle_map = {stage: (pass_key, pass_cls)}
                template = build_bundle_template(f"Standalone: {pass_key}", bundle_map)
            except Exception as e:
                print(f"  Skipping {pass_key}: {e}")
                continue

            for circuit_cls in ALL_CIRCUITS:
                for num_qubits in get_qubits_for_circuit(circuit_cls, qubit_scales):
                    try:
                        initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                    except Exception:
                        continue

                    result = safe_run_pipeline(
                        template, initial_qasm, backend_json,
                        extra_result={
                            "tier": "1_standalone",
                            "bundle_stage": stage,
                            "opt_pass": pass_key,
                            "opt_sequence": pass_key,
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                        },
                    )
                    results.append(result)

    # -----------------------------------------------------------------------
    # Tier 2a: Baseline — no optimization
    # -----------------------------------------------------------------------
    print("\n=== Tier 2a: Baseline (no optimization) ===")
    baseline = RoleBasedCompilationTemplate(
        name="Baseline (No Optimization)",
        bundle_passes={},
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        translation=PresetTranslationPass(),
    )
    baseline.opt_sequence = "none"

    for circuit_cls in tqdm(ALL_CIRCUITS, desc="Baseline"):
        for num_qubits in get_qubits_for_circuit(circuit_cls, qubit_scales):
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
            except Exception:
                continue
            result = safe_run_pipeline(
                baseline, initial_qasm, backend_json,
                extra_result={
                    "tier": "2_baseline",
                    "bundle_stage": "all",
                    "opt_pass": "none",
                    "opt_sequence": "none",
                    "circuit_type": circuit_cls.name,
                    "num_qubits": num_qubits,
                },
            )
            results.append(result)

    # -----------------------------------------------------------------------
    # Tier 2b: Same-SDK full chains
    # -----------------------------------------------------------------------
    print("\n=== Tier 2b: Same-SDK full chains ===")
    for sdk, chain in sdk_chains.items():
        try:
            template = build_bundle_template(f"Full-SDK-Chain: {sdk.upper()}", chain)
        except Exception as e:
            print(f"Skipping {sdk} chain: {e}")
            continue

        print(f"  {sdk.upper()} chain: {template.opt_sequence}")

        for circuit_cls in tqdm(ALL_CIRCUITS, desc=f"Chain: {sdk}", leave=False):
            for num_qubits in get_qubits_for_circuit(circuit_cls, qubit_scales):
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                except Exception:
                    continue
                result = safe_run_pipeline(
                    template, initial_qasm, backend_json,
                    extra_result={
                        "tier": "2_sdk_chain",
                        "bundle_stage": "all",
                        "opt_pass": f"chain_{sdk}",
                        "opt_sequence": template.opt_sequence,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                    },
                )
                results.append(result)

    # -----------------------------------------------------------------------
    # Tier 3: Cross-SDK best-of-stage combo
    # Built after Tier 1 results are available — pick best pass per stage
    # per circuit type at the smallest qubit scale, then run the combined
    # pipeline across all circuits and scales.
    # -----------------------------------------------------------------------
    print("\n=== Tier 3: Cross-SDK best-of-stage combo ===")

    # Identify best pass per stage per circuit from Tier 1
    tier1_df = pd.DataFrame([r for r in results if r.get("tier") == "1_standalone"])

    if not tier1_df.empty and "Circuit Depth" in tier1_df.columns:
        small_scale = min(qubit_scales)
        t1_small = tier1_df[
            (tier1_df["status"] == "success") &
            (tier1_df["num_qubits"] == small_scale)
        ]

        for circuit_cls in ALL_CIRCUITS:
            cname = circuit_cls.name
            circuit_t1 = t1_small[t1_small["circuit_type"] == cname]
            if circuit_t1.empty:
                continue

            # For each stage, pick the pass with lowest depth
            best_per_stage = {}
            for stage in BUNDLE_STAGES:
                stage_rows = circuit_t1[circuit_t1["bundle_stage"] == stage]
                if stage_rows.empty:
                    continue
                best_row = stage_rows.loc[stage_rows["Circuit Depth"].idxmin()]
                best_key = best_row["opt_pass"]
                best_cls = passes_per_stage[stage].get(best_key)
                if best_cls:
                    best_per_stage[stage] = (best_key, best_cls)

            if not best_per_stage:
                continue

            try:
                template = build_bundle_template(
                    f"Cross-SDK-Best: {cname}", best_per_stage
                )
            except Exception as e:
                print(f"  Skipping cross-SDK for {cname}: {e}")
                continue

            print(f"  {cname}: {template.opt_sequence}")

            for num_qubits in get_qubits_for_circuit(circuit_cls, qubit_scales):
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                except Exception:
                    continue
                result = safe_run_pipeline(
                    template, initial_qasm, backend_json,
                    extra_result={
                        "tier": "3_cross_sdk_best",
                        "bundle_stage": "all",
                        "opt_pass": "cross_sdk_best",
                        "opt_sequence": template.opt_sequence,
                        "circuit_type": cname,
                        "num_qubits": num_qubits,
                    },
                )
                results.append(result)
    else:
        print("  Skipping Tier 3 — no Tier 1 results available yet.")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    df = pd.DataFrame(results)
    success = df[df["status"] == "success"]

    if not success.empty and "Circuit Depth" in success.columns:
        print("\n--- Best optimization pass per circuit (Tier 1, depth metric) ---")
        t1_success = success[success["tier"] == "1_standalone"]
        if not t1_success.empty:
            best = t1_success.loc[
                t1_success.groupby(["circuit_type", "num_qubits"])["Circuit Depth"].idxmin()
            ]
            print(best[["circuit_type", "num_qubits", "bundle_stage", "opt_pass", "Circuit Depth"]]
                  .sort_values(["circuit_type", "num_qubits"])
                  .to_string(index=False))

        print("\n--- Tier comparison (mean depth across all circuits) ---")
        print(success.groupby("tier")["Circuit Depth"].mean().round(1).to_string())

    if not args.no_save:
        save_results(df, "exp1_optimization.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 1C: Optimization Specialization")
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)