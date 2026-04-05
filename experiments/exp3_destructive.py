"""
Experiment 3: Destructive Interference (H3)
============================================
Tests whether adding a correct optimization pass to a pipeline can
INCREASE circuit depth, and whether this effect is ordering-dependent.

Protocol:
  1. Start from baseline-compiled circuit (init/layout/routing/translation)
  2. Define 6 optimization passes from 3 SDKs
  3. Apply them incrementally in 3 different orderings
  4. Record depth after each pass addition

Non-monotonic depth curves = destructive interference.
Divergent curves between orderings = ordering dependence.

Hypothesis H3: Adding correct passes can worsen quality, and this
effect is ordering-dependent.
"""

import argparse
import pandas as pd
from tqdm import tqdm

from common import (
    ALL_CIRCUITS,
    ENV_CONFIG_PATH,
    initialize_circuit,
    evaluate,
    get_heavy_hex_backend,
    save_results,
    flush_results,
    QPassContext,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    DefaultCompilationTemplate,
)

# The 6 cross-SDK optimization passes we'll test
from qlego_qiskit.adapter.passes import (
    Optimize1qGateDecompositionPass,
    CommutativeCancellationPass,
)
from qlego_tket.adapter.passes import (
    CliffordSimpPass,
    KAKDecompositionPass,
)
from qlego_bqskit.adapter.passes import (
    ScanningGateRemovalPassPass,
    GroupSingleQuditGatePassPass,
)

# Named pass pool
PASS_POOL = {
    "Qiskit:Optimize1qGateDecomp": Optimize1qGateDecompositionPass,
    "Qiskit:CommutativeCancel": CommutativeCancellationPass,
    "TKet:CliffordSimp": CliffordSimpPass,
    "TKet:KAKDecomposition": KAKDecompositionPass,
    "BQSKit:ScanningGateRemoval": ScanningGateRemovalPassPass,
    "BQSKit:GroupSingleQuditGate": GroupSingleQuditGatePassPass,
}

# 3 orderings of the same 6 passes (alternating SDKs differently)
ORDERINGS = {
    "Order_A (Q-T-B-Q-T-B)": [
        "Qiskit:Optimize1qGateDecomp",
        "TKet:CliffordSimp",
        "BQSKit:ScanningGateRemoval",
        "Qiskit:CommutativeCancel",
        "TKet:KAKDecomposition",
        "BQSKit:GroupSingleQuditGate",
    ],
    "Order_B (T-B-Q-T-B-Q)": [
        "TKet:CliffordSimp",
        "BQSKit:ScanningGateRemoval",
        "Qiskit:Optimize1qGateDecomp",
        "TKet:KAKDecomposition",
        "BQSKit:GroupSingleQuditGate",
        "Qiskit:CommutativeCancel",
    ],
    "Order_C (B-Q-T-B-Q-T)": [
        "BQSKit:ScanningGateRemoval",
        "Qiskit:Optimize1qGateDecomp",
        "TKet:CliffordSimp",
        "BQSKit:GroupSingleQuditGate",
        "Qiskit:CommutativeCancel",
        "TKet:KAKDecomposition",
    ],
}


def run(args):
    _, backend_json = get_heavy_hex_backend()

    qubit_scales = args.qubits or [5, 10]
    results = []

    total = len(qubit_scales) * len(ALL_CIRCUITS) * len(ORDERINGS)
    pbar = tqdm(total=total, desc="Exp 3: Destructive Interference")

    for num_qubits in qubit_scales:
        for circuit_cls in ALL_CIRCUITS:
            # Step 1: Generate baseline compiled circuit
            try:
                initial_qasm = initialize_circuit(circuit_cls, num_qubits)
                baseline_template = DefaultCompilationTemplate(
                    initialization=PresetInitPass(),
                    layout=PresetLayoutPass(),
                    routing=PresetRoutingPass(),
                    optimization=[],
                    translation=PresetTranslationPass(),
                )
                ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
                compiled_ctx = baseline_template.compile(ctx=ctx, env_config_path=ENV_CONFIG_PATH)
                baseline_qasm = compiled_ctx.qasm
                baseline_metrics = evaluate(baseline_qasm)
            except Exception as e:
                print(f"Baseline failed for {circuit_cls.name} {num_qubits}q: {e}")
                pbar.update(len(ORDERINGS))
                continue

            # Record baseline
            results.append({
                "circuit_type": circuit_cls.name,
                "num_qubits": num_qubits,
                "ordering": "ALL",
                "step": 0,
                "pass_name": "Baseline (no optimization)",
                "Circuit Depth": baseline_metrics.get("Circuit Depth"),
                "Gate Count": baseline_metrics.get("Gate Count"),
                "2Q Count": baseline_metrics.get("2Q Count"),
                "2Q Depth": baseline_metrics.get("2Q Depth"),
                "status": "success",
                "error": "",
            })

            # Step 2: For each ordering, apply passes incrementally
            for ordering_name, pass_sequence in ORDERINGS.items():
                pbar.set_postfix_str(
                    f"{circuit_cls.name} {num_qubits}q {ordering_name}"
                )
                current_qasm = baseline_qasm

                for step_idx, pass_name in enumerate(pass_sequence, start=1):
                    pass_cls = PASS_POOL[pass_name]
                    try:
                        opt_template = DefaultCompilationTemplate(
                            initialization=[],
                            layout=[],
                            routing=[],
                            optimization=pass_cls(),
                            translation=[],
                        )
                        ctx = QPassContext(qasm=current_qasm, hardware=backend_json)
                        compiled_ctx = opt_template.compile(ctx=ctx, env_config_path=ENV_CONFIG_PATH)
                        current_qasm = compiled_ctx.qasm
                        metrics = evaluate(current_qasm)

                        results.append({
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                            "ordering": ordering_name,
                            "step": step_idx,
                            "pass_name": pass_name,
                            "Circuit Depth": metrics.get("Circuit Depth"),
                            "Gate Count": metrics.get("Gate Count"),
                            "2Q Count": metrics.get("2Q Count"),
                            "2Q Depth": metrics.get("2Q Depth"),
                            "status": "success",
                            "error": "",
                        })
                    except Exception as e:
                        results.append({
                            "circuit_type": circuit_cls.name,
                            "num_qubits": num_qubits,
                            "ordering": ordering_name,
                            "step": step_idx,
                            "pass_name": pass_name,
                            "status": "failed",
                            "error": str(e)[:200],
                        })
                        # Don't break — continue with same qasm for next pass

                pbar.update(1)

        if not args.no_save:
            flush_results(results, "exp3_destructive.csv", pbar)

    pbar.close()
    df = pd.DataFrame(results)

    # Analysis: find destructive instances
    success = df[df["status"] == "success"].copy()
    if not success.empty and "Circuit Depth" in success.columns:
        destructive_count = 0
        for (circ, nq, order), group in success.groupby(
            ["circuit_type", "num_qubits", "ordering"]
        ):
            group = group.sort_values("step")
            depths = group["Circuit Depth"].tolist()
            for i in range(1, len(depths)):
                if depths[i] > depths[i - 1]:
                    destructive_count += 1
        print(f"\nDestructive interference instances: {destructive_count}")

    if not args.no_save:
        save_results(df, "exp3_destructive.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 3: Destructive Interference")
    parser.add_argument("--qubits", type=int, nargs="+", default=None)
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
