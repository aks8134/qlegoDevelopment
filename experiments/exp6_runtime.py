"""
Experiment 6: Runtime Comparison
==================================
Compares wall-clock compilation time across SDKs and pass categories
at multiple qubit scales. Addresses the practical question: does
cross-framework compilation incur significant overhead?

Three dimensions measured:
  A) Per-pass runtime: individual passes from each SDK (layout, routing, optim)
  B) Full pipeline runtime: end-to-end single-SDK vs cross-SDK pipelines
  C) Scaling behavior: how runtime grows with qubit count

Time data is extracted from ctx.metadata["time_profile"] which records
wall/cpu/non_cpu seconds for each pass in the pipeline.

Key metrics:
  - wall_seconds: total elapsed time (includes subprocess overhead)
  - cpu_seconds: actual CPU time inside the pass
  - overhead_seconds: wall - cpu (subprocess serialization cost)
"""

import argparse
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    SCALE_QUBITS,
    initialize_circuit,
    get_heavy_hex_backend,
    ensure_registry,
    save_results,
    flush_results,
    ENV_CONFIG_PATH,
    QPassContext,
    QPipeline,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PassRegistry,
    DefaultCompilationTemplate,
)

# Cross-SDK pipeline definitions for Part B
from qlego_qiskit.adapter.passes import (
    SabreLayoutPass,
    SabreSwapRoutingPass,
    Optimize1qGateDecompositionPass,
    CommutativeCancellationPass,
)
from qlego_tket.adapter.passes import (
    GraphPlacementPass,
    TketDefaultRoutingPass,
    CliffordSimpPass,
    FullPeepholeOptimizePass,
)
from qlego_bqskit.adapter.passes import (
    GeneralizedSabrePass,
    GeneralizedSabreRoutingPass,
    ScanningGateRemovalPassPass,
    GroupSingleQuditGatePassPass,
)

# Representative circuit subset for runtime (avoids very slow circuits)
RUNTIME_CIRCUITS = [
    c for c in ALL_CIRCUITS
    if c.name in ["DJ Circuit", "GHZ Circuit", "QFT Circuit",
                   "W State Circuit", "Grover Circuit"]
]

# Full qubit scale range to show scaling behavior
RUNTIME_QUBITS = [5, 10, 15, 20]


def extract_timing(ctx) -> dict:
    """Extract per-pass timing from ctx.metadata['time_profile']."""
    profile = ctx.metadata.get("time_profile", {})
    timings = {}
    for pass_name, data in profile.items():
        pass_timing = data.get("pass", {})
        timings[pass_name] = {
            "wall": pass_timing.get("wall", 0.0),
            "cpu": pass_timing.get("cpu", 0.0),
            "overhead": pass_timing.get("non_cpu", 0.0),
        }
    return timings


def run_and_time(template, initial_qasm, backend_json, extra_fields=None):
    """
    Run a template and return a list of per-pass timing rows.
    Each row = one pass with its timing and the extra_fields.
    """
    rows = []
    base = dict(extra_fields or {})
    try:
        ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
        compiled_ctx = template.compile(ctx=ctx, env_config_path=ENV_CONFIG_PATH)
        timings = extract_timing(compiled_ctx)

        for pass_name, t in timings.items():
            row = {**base}
            row["pass_name"] = pass_name
            row["wall_s"] = round(t["wall"], 4)
            row["cpu_s"] = round(t["cpu"], 4)
            row["overhead_s"] = round(t["overhead"], 4)
            row["status"] = "success"
            row["error"] = ""
            rows.append(row)

        # Also record total pipeline wall time
        total_wall = sum(t["wall"] for t in timings.values())
        total_row = {**base}
        total_row["pass_name"] = "__TOTAL__"
        total_row["wall_s"] = round(total_wall, 4)
        total_row["cpu_s"] = round(sum(t["cpu"] for t in timings.values()), 4)
        total_row["overhead_s"] = round(sum(t["overhead"] for t in timings.values()), 4)
        total_row["status"] = "success"
        total_row["error"] = ""
        rows.append(total_row)

    except Exception as e:
        err = str(e)[:200]
        rows.append({**base, "pass_name": "__FAILED__",
                     "wall_s": None, "cpu_s": None, "overhead_s": None,
                     "status": "failed", "error": err})
    return rows


# -----------------------------------------------------------------------
# Part A: Per-pass runtime (all registered passes, standalone)
# -----------------------------------------------------------------------

def run_part_a(args, backend_json):
    """Individual pass runtime across all categories and SDKs."""
    ensure_registry()

    results = []
    categories = ["Layout", "Routing", "Optimization"]

    for category in categories:
        passes = PassRegistry.get_passes_by_category(category)
        print(f"\nPart A — {category}: {len(passes)} passes")

        for num_qubits in RUNTIME_QUBITS:
            for circuit_cls in RUNTIME_CIRCUITS:
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                except Exception:
                    continue

                for pass_key, pass_cls in tqdm(
                    passes.items(),
                    desc=f"{category} | {circuit_cls.name} {num_qubits}q",
                    leave=False,
                ):
                    try:
                        if category == "Layout":
                            t = DefaultCompilationTemplate(
                                initialization=PresetInitPass(),
                                layout=pass_cls(),
                                routing=PresetRoutingPass(),
                                optimization=[],
                                translation=PresetTranslationPass(),
                            )
                        elif category == "Routing":
                            t = DefaultCompilationTemplate(
                                initialization=PresetInitPass(),
                                layout=PresetLayoutPass(),
                                routing=pass_cls(),
                                optimization=[],
                                translation=PresetTranslationPass(),
                            )
                        else:  # Optimization
                            t = DefaultCompilationTemplate(
                                initialization=PresetInitPass(),
                                layout=PresetLayoutPass(),
                                routing=PresetRoutingPass(),
                                optimization=pass_cls(),
                                translation=PresetTranslationPass(),
                            )
                    except Exception:
                        continue

                    rows = run_and_time(
                        t, initial_qasm, backend_json,
                        extra_fields={
                            "part": "A_per_pass",
                            "category": category,
                            "sdk": pass_key.split("_")[0].replace("qlego-", ""),
                            "pass_key": pass_key,
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                            "pipeline_type": "single_pass",
                        },
                    )
                    results.extend(rows)

    return results


# -----------------------------------------------------------------------
# Part B: Full pipeline runtime — single-SDK vs cross-SDK
# -----------------------------------------------------------------------

PIPELINES = {
    # Single-SDK baselines
    "Qiskit (end-to-end)": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=SabreLayoutPass(),
        routing=SabreSwapRoutingPass(),
        optimization=[Optimize1qGateDecompositionPass(), CommutativeCancellationPass()],
        translation=PresetTranslationPass(),
    ),
    "TKet (end-to-end)": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=GraphPlacementPass(),
        routing=TketDefaultRoutingPass(),
        optimization=[CliffordSimpPass(), FullPeepholeOptimizePass()],
        translation=PresetTranslationPass(),
    ),
    "BQSKit (end-to-end)": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=GeneralizedSabrePass(),
        routing=GeneralizedSabreRoutingPass(),
        optimization=[GroupSingleQuditGatePassPass(), ScanningGateRemovalPassPass()],
        translation=PresetTranslationPass(),
    ),
    # Cross-SDK hybrids
    "Cross-SDK: Qiskit layout + TKet optim": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=SabreLayoutPass(),
        routing=SabreSwapRoutingPass(),
        optimization=[CliffordSimpPass(), FullPeepholeOptimizePass()],
        translation=PresetTranslationPass(),
    ),
    "Cross-SDK: BQSKit layout + TKet optim": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=GeneralizedSabrePass(),
        routing=TketDefaultRoutingPass(),
        optimization=[CliffordSimpPass(), ScanningGateRemovalPassPass()],
        translation=PresetTranslationPass(),
    ),
    "Cross-SDK: Qiskit layout + BQSKit+TKet optim": DefaultCompilationTemplate(
        initialization=PresetInitPass(),
        layout=SabreLayoutPass(),
        routing=SabreSwapRoutingPass(),
        optimization=[
            GroupSingleQuditGatePassPass(),
            CliffordSimpPass(),
            Optimize1qGateDecompositionPass(),
        ],
        translation=PresetTranslationPass(),
    ),
}


def run_part_b(args, backend_json):
    """Full pipeline runtime comparison — single-SDK vs cross-SDK."""
    results = []
    print(f"\nPart B — Full pipelines: {len(PIPELINES)}")

    for num_qubits in RUNTIME_QUBITS:
        for circuit_cls in RUNTIME_CIRCUITS:
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
            except Exception:
                continue

            for pipeline_name, template in tqdm(
                PIPELINES.items(),
                desc=f"Pipelines | {circuit_cls.name} {num_qubits}q",
                leave=False,
            ):
                sdk_type = "cross_sdk" if "Cross-SDK" in pipeline_name else "single_sdk"
                rows = run_and_time(
                    template, initial_qasm, backend_json,
                    extra_fields={
                        "part": "B_full_pipeline",
                        "pipeline_name": pipeline_name,
                        "sdk_type": sdk_type,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                    },
                )
                results.extend(rows)

    return results


# -----------------------------------------------------------------------
# Part C: Scaling behavior (total wall time vs qubit count)
# -----------------------------------------------------------------------

def run_part_c(args, backend_json):
    """How does runtime scale with qubit count?"""
    results = []
    qubit_scales = args.qubits or SCALE_QUBITS
    print(f"\nPart C — Scaling: {qubit_scales}q")

    reference_pipelines = {
        k: v for k, v in PIPELINES.items()
        if k in ["Qiskit (end-to-end)", "TKet (end-to-end)",
                  "Cross-SDK: BQSKit layout + TKet optim"]
    }

    for circuit_cls in RUNTIME_CIRCUITS:
        for num_qubits in tqdm(qubit_scales, desc=f"Scaling | {circuit_cls.name}"):
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
            except Exception:
                continue

            for pipeline_name, template in reference_pipelines.items():
                rows = run_and_time(
                    template, initial_qasm, backend_json,
                    extra_fields={
                        "part": "C_scaling",
                        "pipeline_name": pipeline_name,
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                    },
                )
                results.extend(rows)

    return results


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def run(args):
    _, backend_json = get_heavy_hex_backend()
    all_results = []

    if not args.skip_a:
        all_results.extend(run_part_a(args, backend_json))
        if not args.no_save:
            flush_results(all_results, "exp6_runtime.csv")

    if not args.skip_b:
        all_results.extend(run_part_b(args, backend_json))
        if not args.no_save:
            flush_results(all_results, "exp6_runtime.csv")

    if not args.skip_c:
        all_results.extend(run_part_c(args, backend_json))
        if not args.no_save:
            flush_results(all_results, "exp6_runtime.csv")

    df = pd.DataFrame(all_results)

    # Summary
    totals = df[(df["pass_name"] == "__TOTAL__") & (df["status"] == "success")]
    if not totals.empty:
        print("\n--- Average total pipeline wall time by SDK type ---")
        if "sdk_type" in totals.columns:
            print(totals.groupby("sdk_type")["wall_s"].mean().round(3).to_string())

        print("\n--- Average total wall time by pipeline (Part B) ---")
        partb = totals[totals.get("part", pd.Series()) == "B_full_pipeline"] if "part" in totals.columns else pd.DataFrame()
        if not partb.empty:
            print(partb.groupby("pipeline_name")["wall_s"]
                  .mean().sort_values().round(3).to_string())

    if not args.no_save:
        save_results(df, "exp6_runtime.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 6: Runtime Comparison")
    parser.add_argument("--qubits", type=int, nargs="+", default=None,
                        help="Qubit scales for Part C (default: 5 10 15 20 25 30)")
    parser.add_argument("--skip_a", action="store_true", help="Skip per-pass timing (Part A)")
    parser.add_argument("--skip_b", action="store_true", help="Skip full pipeline timing (Part B)")
    parser.add_argument("--skip_c", action="store_true", help="Skip scaling analysis (Part C)")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
