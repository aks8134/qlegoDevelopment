"""
Experiment 2: Cross-SDK Complementarity (H2)
=============================================
Tests whether optimization passes from different SDKs explore different
regions of the optimization landscape.

Protocol:
  1. Compile circuit through neutral init/layout/routing/translation
  2. Apply SDK_A's optimization chain iteratively until fixed-point
     (depth reduction < 0.1% between iterations)
  3. Record metrics at convergence: M_A
  4. Apply SDK_B's chain -> record M_AB
  5. Apply SDK_C's chain -> record M_ABC
  6. Compute residual improvement at each step

All 6 permutations of (Qiskit, TKet, BQSKit) are tested.

Hypothesis H2: After one SDK's optimizer converges, a different SDK
can still extract additional reductions.
"""

import argparse
import itertools
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    STANDARD_QUBITS,
    initialize_circuit,
    evaluate,
    get_heavy_hex_backend,
    save_results,
    QPassContext,
    QPipeline,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    DefaultCompilationTemplate,
)

# Import SDK-specific optimization passes
from qlego_qiskit.adapter.passes import (
    Optimize1qGateDecompositionPass,
    CommutativeCancellationPass,
    OptimizeCliffordsPass,
    Collect2qBlocksPass,
    RemoveIdentityEquivalentPass,
)
from qlego_tket.adapter.passes import (
    FullPeepholeOptimizePass,
    CliffordSimpPass,
    KAKDecompositionPass,
    RemoveRedundanciesPass,
)
from qlego_bqskit.adapter.passes import (
    GroupSingleQuditGatePassPass,
    ScanningGateRemovalPassPass,
    QuickPartitionerPass,
)


# SDK optimization chains
SDK_CHAINS = {
    "Qiskit": [
        Optimize1qGateDecompositionPass,
        CommutativeCancellationPass,
        OptimizeCliffordsPass,
        Collect2qBlocksPass,
        RemoveIdentityEquivalentPass,
    ],
    "TKet": [
        FullPeepholeOptimizePass,
        CliffordSimpPass,
        KAKDecompositionPass,
        RemoveRedundanciesPass,
    ],
    "BQSKit": [
        GroupSingleQuditGatePassPass,
        ScanningGateRemovalPassPass,
        QuickPartitionerPass,
    ],
}

CONVERGENCE_THRESHOLD = 0.001  # 0.1% relative improvement
MAX_ITERATIONS = 10


def apply_chain_to_convergence(qasm, backend_json, chain_classes):
    """
    Apply an SDK's optimization chain iteratively until convergence.
    Returns (final_qasm, metrics_at_convergence, num_iterations).
    """
    current_qasm = qasm
    prev_depth = None

    for iteration in range(MAX_ITERATIONS):
        # Build and run the chain
        passes = [cls() for cls in chain_classes]
        t = DefaultCompilationTemplate(
            initialization=[],
            layout=[],
            routing=[],
            optimization=passes,
            translation=[],
        )
        try:
            ctx = QPassContext(qasm=current_qasm, hardware=backend_json)
            compiled_ctx = t.compile(ctx=ctx)
            current_qasm = compiled_ctx.qasm
        except Exception:
            break

        metrics = evaluate(current_qasm)
        depth = metrics.get("Circuit Depth", 0)

        # Check convergence
        if prev_depth is not None and prev_depth > 0:
            improvement = (prev_depth - depth) / prev_depth
            if improvement < CONVERGENCE_THRESHOLD:
                return current_qasm, metrics, iteration + 1

        prev_depth = depth

    # Return after max iterations
    metrics = evaluate(current_qasm)
    return current_qasm, metrics, MAX_ITERATIONS


def apply_chain_once(qasm, backend_json, chain_classes):
    """Apply an SDK chain once (no convergence loop). Returns (qasm, metrics)."""
    passes = [cls() for cls in chain_classes]
    t = DefaultCompilationTemplate(
        initialization=[],
        layout=[],
        routing=[],
        optimization=passes,
        translation=[],
    )
    try:
        ctx = QPassContext(qasm=qasm, hardware=backend_json)
        compiled_ctx = t.compile(ctx=ctx)
        metrics = evaluate(compiled_ctx.qasm)
        return compiled_ctx.qasm, metrics
    except Exception as e:
        return qasm, {"error": str(e)[:200]}


def run(args):
    _, backend_json = get_heavy_hex_backend()

    qubit_scales = args.qubits or STANDARD_QUBITS
    sdk_names = list(SDK_CHAINS.keys())
    orderings = list(itertools.permutations(sdk_names))

    results = []

    total = len(qubit_scales) * len(ALL_CIRCUITS) * len(orderings)
    pbar = tqdm(total=total, desc="Exp 2: Complementarity")

    for num_qubits in qubit_scales:
        for circuit_cls in ALL_CIRCUITS:
            # Step 1: Generate and compile through neutral baseline
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                # Compile through init/layout/routing/translation (no optimization)
                baseline_template = DefaultCompilationTemplate(
                    initialization=PresetInitPass(),
                    layout=PresetLayoutPass(),
                    routing=PresetRoutingPass(),
                    optimization=[],
                    translation=PresetTranslationPass(),
                )
                ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
                compiled_ctx = baseline_template.compile(ctx=ctx)
                baseline_qasm = compiled_ctx.qasm
                baseline_metrics = evaluate(baseline_qasm)
            except Exception as e:
                print(f"Baseline failed for {circuit_cls.name} {num_qubits}q: {e}")
                pbar.update(len(orderings))
                continue

            # Step 2: For each ordering, apply SDKs sequentially
            for ordering in orderings:
                pbar.set_postfix_str(
                    f"{circuit_cls.name} {num_qubits}q {'->'.join(ordering)}"
                )

                row = {
                    "circuit_type": circuit_cls.name,
                    "num_qubits": num_qubits,
                    "ordering": " -> ".join(ordering),
                    "baseline_depth": baseline_metrics.get("Circuit Depth"),
                    "baseline_gates": baseline_metrics.get("Gate Count"),
                    "baseline_2q": baseline_metrics.get("2Q Count"),
                    "status": "success",
                    "error": "",
                }

                current_qasm = baseline_qasm
                try:
                    for step_idx, sdk_name in enumerate(ordering):
                        chain = SDK_CHAINS[sdk_name]

                        if step_idx == 0:
                            # First SDK: converge to fixed-point
                            current_qasm, metrics, iters = apply_chain_to_convergence(
                                current_qasm, backend_json, chain
                            )
                            row[f"step{step_idx}_sdk"] = sdk_name
                            row[f"step{step_idx}_converged_iters"] = iters
                        else:
                            # Subsequent SDKs: apply once
                            current_qasm, metrics = apply_chain_once(
                                current_qasm, backend_json, chain
                            )
                            row[f"step{step_idx}_sdk"] = sdk_name

                        row[f"step{step_idx}_depth"] = metrics.get("Circuit Depth")
                        row[f"step{step_idx}_gates"] = metrics.get("Gate Count")
                        row[f"step{step_idx}_2q"] = metrics.get("2Q Count")

                    # Compute residual improvements
                    for step_idx in range(1, len(ordering)):
                        prev_depth = row.get(f"step{step_idx-1}_depth")
                        curr_depth = row.get(f"step{step_idx}_depth")
                        if prev_depth and curr_depth and prev_depth > 0:
                            row[f"step{step_idx}_residual_pct"] = round(
                                100.0 * (prev_depth - curr_depth) / prev_depth, 2
                            )
                        else:
                            row[f"step{step_idx}_residual_pct"] = None

                except Exception as e:
                    row["status"] = "failed"
                    row["error"] = str(e)[:200]

                results.append(row)
                pbar.update(1)

    pbar.close()
    df = pd.DataFrame(results)

    # Summary: average residual improvement per SDK pair
    success = df[df["status"] == "success"]
    if not success.empty and "step1_residual_pct" in success.columns:
        print("\n--- Residual improvement after convergence (step1) ---")
        print(success.groupby("ordering")["step1_residual_pct"].mean().to_string())

    if not args.no_save:
        save_results(df, "exp2_complementarity.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 2: Cross-SDK Complementarity")
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
