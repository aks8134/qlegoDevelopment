"""
Experiment 1C: Optimization Pass Domain Specialization (H1)
===========================================================
Evaluates optimization pass pipelines by sampling the cross-stage combination
space using the RoleBasedCompilationTemplate (6 semantic bundle stages).

Pipeline set:
  - Baseline: no optimization (always included)
  - SDK chains: full Qiskit / TKet / BQSKit chains (always included)
  - Random samples: N randomly sampled cross-stage combos (--max_pipelines controls N)

Each pipeline is run on all circuit families at all qubit scales.

Hypothesis H1: The optimal optimization pass depends on circuit structure;
no single SDK dominates across all circuit families.
"""

import argparse
import os
import random
import pandas as pd
from tqdm import tqdm

import common
common.TIMEOUT_SECONDS = 50  # Shorter cutoff for optimization passes

from common import (
    ALL_CIRCUITS,
    STANDARD_QUBITS,
    get_qubits_for_circuit,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    safe_run_pipeline,
    save_results,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
)
from qlego_generator.bundled_template import RoleBasedCompilationTemplate, BUNDLE_STAGES


def get_passes_per_stage(exclude_sdks=("cirq",)):
    """Return {stage: {pass_key: pass_cls}} for all bundle stages."""
    ensure_registry()
    result = {}
    for stage in BUNDLE_STAGES:
        passes = PassRegistry.get_passes_by_category(stage)
        result[stage] = {
            k: v for k, v in passes.items()
            if not any(sdk in k.lower() for sdk in exclude_sdks)
        }
    return result


def build_bundle_template(name, bundle_pass_map):
    """
    Build a RoleBasedCompilationTemplate from a {stage: (key, cls)} map.
    Stages absent from bundle_pass_map are left empty.
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


def make_sdk_chain_template(sdk, passes_per_stage):
    """Build a full same-SDK chain by picking the first pass per stage for that SDK."""
    chain = {}
    for stage, stage_passes in passes_per_stage.items():
        sdk_passes = {k: v for k, v in stage_passes.items() if sdk in k.lower()}
        if sdk_passes:
            key, cls = next(iter(sdk_passes.items()))
            chain[stage] = (key, cls)
    if not chain:
        return None
    return build_bundle_template(f"Chain: {sdk.upper()}", chain)


def sample_random_pipelines(passes_per_stage, n, seed=42):
    """
    Sample n distinct random pipelines from the cross-stage combination space.
    Each pipeline independently picks 0 or 1 pass per stage (skip = empty stage).
    Returns list of (name, bundle_pass_map) tuples.
    """
    rng = random.Random(seed)
    # Build flat list per stage: [None (skip), key1, key2, ...]
    stage_options = {
        stage: [None] + list(passes.keys())
        for stage, passes in passes_per_stage.items()
    }

    seen_sequences = set()
    pipelines = []

    attempts = 0
    while len(pipelines) < n and attempts < n * 20:
        attempts += 1
        bundle_map = {}
        for stage, options in stage_options.items():
            choice = rng.choice(options)
            if choice is not None:
                bundle_map[stage] = (choice, passes_per_stage[stage][choice])

        seq = " -> ".join(bundle_map[s][0] for s in BUNDLE_STAGES if s in bundle_map) or "none"
        if seq in seen_sequences:
            continue
        seen_sequences.add(seq)
        pipelines.append((f"Random: {seq[:60]}", bundle_map))

    return pipelines


def run(args):
    print("Loading backend...")
    _, backend_json = get_heavy_hex_backend()
    qubit_scales = args.qubits or STANDARD_QUBITS
    print(f"Qubit scales: {qubit_scales}")

    # Resume: load already-completed (opt_sequence, circuit_type, num_qubits) triples
    completed_keys = set()
    out_file = "exp1_optimization.csv"
    resume_path = os.path.join(common.RESULTS_DIR, out_file)
    if args.resume and os.path.exists(resume_path):
        df_prev = pd.read_csv(resume_path)
        for _, row in df_prev.iterrows():
            completed_keys.add((row["opt_sequence"], row["circuit_type"], int(row["num_qubits"])))
        print(f"Resuming: {len(completed_keys)} completed (circuit, pipeline) pairs found.")

    print("Loading pass registry...")
    passes_per_stage = get_passes_per_stage()
    for stage, passes in passes_per_stage.items():
        print(f"  {stage}: {len(passes)} passes")

    # -----------------------------------------------------------------------
    # Build the pipeline set
    # -----------------------------------------------------------------------
    templates = []  # list of (template, pipeline_type) tuples

    # 1. Baseline
    baseline = RoleBasedCompilationTemplate(
        name="Baseline (No Optimization)",
        bundle_passes={},
        initialization=PresetInitPass(),
        layout=PresetLayoutPass(),
        routing=PresetRoutingPass(),
        translation=PresetTranslationPass(),
    )
    baseline.opt_sequence = "none"
    templates.append((baseline, "baseline"))

    # 2. SDK chains
    for sdk in ("qiskit", "tket", "bqskit"):
        t = make_sdk_chain_template(sdk, passes_per_stage)
        if t:
            templates.append((t, f"sdk_chain_{sdk}"))
            print(f"  Chain {sdk.upper()}: {t.opt_sequence}")

    # 3. Random samples (fill up to max_pipelines)
    n_random = max(0, args.max_pipelines - len(templates))
    print(f"\nSampling {n_random} random pipelines (total budget: {args.max_pipelines})...")
    sampled = sample_random_pipelines(passes_per_stage, n_random, seed=args.seed)
    for name, bundle_map in sampled:
        try:
            t = build_bundle_template(name, bundle_map)
            templates.append((t, "random_sample"))
        except Exception as e:
            print(f"  Skipping '{name}': {e}")

    print(f"Total pipelines to evaluate: {len(templates)}")

    # -----------------------------------------------------------------------
    # Run all pipelines on all circuits × qubit scales
    # Flush results to CSV after each pipeline completes.
    # -----------------------------------------------------------------------
    results = []
    total = sum(
        len(get_qubits_for_circuit(c, qubit_scales)) for c in ALL_CIRCUITS
    ) * len(templates)
    pbar = tqdm(total=total, desc="Exp 1C: Optimization")

    for pipeline_idx, (template, pipeline_type) in enumerate(templates, 1):
        batch = []
        for circuit_cls in ALL_CIRCUITS:
            for num_qubits in get_qubits_for_circuit(circuit_cls, qubit_scales):
                pbar.set_postfix_str(f"{circuit_cls.name} {num_qubits}q | {template.name[:40]}")
                if (template.opt_sequence, circuit_cls.name, int(num_qubits)) in completed_keys:
                    pbar.update(1)
                    continue
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                except Exception:
                    pbar.update(1)
                    continue

                result = safe_run_pipeline(
                    template, initial_qasm, backend_json,
                    extra_result={
                        "pipeline_type": pipeline_type,
                        "opt_sequence": template.opt_sequence,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                    },
                )
                batch.append(result)
                pbar.update(1)

        results.extend(batch)

        # Flush after every pipeline batch (merge with prior results on resume)
        if not args.no_save and batch:
            df_new = pd.DataFrame(results)
            if args.resume and os.path.exists(resume_path):
                df_new = pd.concat([pd.read_csv(resume_path), df_new], ignore_index=True)
            save_results(df_new, out_file)
            pbar.write(f"  [{pipeline_idx}/{len(templates)}] Flushed {len(df_new)} rows → {out_file}")

    pbar.close()

    # -----------------------------------------------------------------------
    # Summary (merge with prior results when resuming)
    # -----------------------------------------------------------------------
    df_new = pd.DataFrame(results)
    if args.resume and os.path.exists(resume_path) and not df_new.empty:
        df = pd.concat([pd.read_csv(resume_path), df_new], ignore_index=True)
    else:
        df = df_new

    if "status" not in df.columns or df.empty:
        print("\nNo results collected.")
        if not args.no_save and not df.empty:
            save_results(df, out_file)
        return

    success = df[df["status"] == "success"]

    if not success.empty and "Circuit Depth" in success.columns:
        print("\n--- Best optimization pipeline per circuit ---")
        best = success.loc[
            success.groupby(["circuit_type", "num_qubits"])["Circuit Depth"].idxmin()
        ]
        print(best[["circuit_type", "num_qubits", "pipeline_type", "opt_sequence", "Circuit Depth"]]
              .sort_values(["circuit_type", "num_qubits"])
              .to_string(index=False))

        print("\n--- Mean depth by pipeline type ---")
        print(success.groupby("pipeline_type")["Circuit Depth"].mean().round(1).to_string())

        print("\n--- Baseline vs best random (mean depth reduction) ---")
        base = success[success["pipeline_type"] == "baseline"]["Circuit Depth"].mean()
        best_rand = success[success["pipeline_type"] == "random_sample"]["Circuit Depth"].mean()
        if base and best_rand:
            print(f"  Baseline mean depth:      {base:.1f}")
            print(f"  Best random sample mean:  {best_rand:.1f}")
            print(f"  Reduction:                {100*(base-best_rand)/base:.1f}%")

    if not args.no_save:
        save_results(df, out_file)  # Final flush with complete data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 1C: Optimization Specialization")
    parser.add_argument("--qubits", type=int, nargs="+", default=None,
                        help="Qubit scales (default: 5 10 15 20)")
    parser.add_argument("--max_pipelines", type=int, default=50,
                        help="Total number of pipelines to evaluate (includes baseline + SDK chains)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed runs found in the existing CSV")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for pipeline sampling")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)