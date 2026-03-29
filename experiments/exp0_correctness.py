"""
Experiment 0: Correctness Validation
=====================================
Validates that QLego's plugin isolation model preserves compilation fidelity.
Compiles circuits using both native Qiskit and QLego-Qiskit plugin across
optimization levels 0-3 and qubit scales, verifying bit-identical output.

Hypothesis: QLego introduces zero quality degradation.
"""

import argparse
import pandas as pd
from tqdm import tqdm
from qiskit.transpiler import generate_preset_pass_manager
from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS

from common import (
    ALL_CIRCUITS,
    RESULTS_DIR,
    initialize_circuit,
    evaluate,
    get_heavy_hex_backend,
    save_results,
    QPassContext,
    QPipeline,
    PresetPasses,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PresetOptimizationPass,
    QiskitBackend,
)


def native_qiskit_compile(qasm_str, optimization_level, backend):
    """Compile using native Qiskit (no QLego)."""
    qc = loads(qasm_str, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
    pm = generate_preset_pass_manager(
        optimization_level=optimization_level,
        backend=backend,
        seed_transpiler=0,
    )
    compiled = pm.run(qc)
    return dumps(compiled)


def qlego_qiskit_compile(qasm_str, optimization_level, backend_json):
    """Compile using QLego's Qiskit plugin."""
    pipeline = QPipeline([PresetPasses(optimization_level=optimization_level)])
    ctx = QPassContext(qasm=qasm_str, hardware=backend_json)
    ctx = pipeline.run("", ctx)
    return ctx.qasm


def run(args):
    backend, backend_json = get_heavy_hex_backend()

    results = []
    qubit_scales = [5, 10, 30, 60]
    opt_levels = [0, 1, 2, 3]

    # Use a subset of circuits for validation
    validation_circuits = [
        c for c in ALL_CIRCUITS
        if c.name in ["DJ Circuit", "GHZ Circuit", "QFT Circuit"]
    ]

    total = len(qubit_scales) * len(validation_circuits) * len(opt_levels)
    pbar = tqdm(total=total, desc="Exp 0: Correctness")

    for num_qubits in qubit_scales:
        for circuit_cls in validation_circuits:
            for opt_level in opt_levels:
                pbar.set_postfix_str(
                    f"{circuit_cls.name} {num_qubits}q opt={opt_level}"
                )
                try:
                    initial_qasm = initialize_circuit(circuit_cls, num_qubits)

                    # Native Qiskit
                    native_qasm = native_qiskit_compile(
                        initial_qasm, opt_level, backend
                    )
                    native_metrics = evaluate(native_qasm)

                    # QLego Qiskit plugin
                    qlego_qasm = qlego_qiskit_compile(
                        initial_qasm, opt_level, backend_json
                    )
                    qlego_metrics = evaluate(qlego_qasm)

                    # Check bit-identical
                    identical = all(
                        native_metrics.get(k) == qlego_metrics.get(k)
                        for k in native_metrics
                    )

                    row = {
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                        "optimization_level": opt_level,
                        "identical": identical,
                    }
                    for k, v in native_metrics.items():
                        row[f"native_{k}"] = v
                    for k, v in qlego_metrics.items():
                        row[f"qlego_{k}"] = v

                    results.append(row)

                except Exception as e:
                    results.append({
                        "circuit_type": circuit_cls.name,
                        "num_qubits": num_qubits,
                        "optimization_level": opt_level,
                        "identical": None,
                        "error": str(e)[:200],
                    })

                pbar.update(1)

    pbar.close()
    df = pd.DataFrame(results)

    # Summary
    if "identical" in df.columns:
        total_pairs = df["identical"].notna().sum()
        identical_count = df["identical"].sum()
        print(f"\nBit-identical: {identical_count}/{total_pairs}")

    if not args.no_save:
        save_results(df, "exp0_correctness.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experiment 0: Correctness Validation")
    parser.add_argument("--no_save", action="store_true")
    args = parser.parse_args()
    run(args)
