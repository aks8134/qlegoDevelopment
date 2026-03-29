"""
Shared utilities for all paper experiments.
"""

import os
import sys
import subprocess
import pandas as pd
from dataclasses import dataclass
from typing import List, Optional

# Add tests dir to path so we can reuse existing infrastructure
TESTS_DIR = os.path.join(os.path.dirname(__file__), "..", "tests")
sys.path.insert(0, TESTS_DIR)

from qlego.qpass import QPipeline, QPassContext
from qlego_mqt_workload.adapter.passes import (
    DJCircuitInitialization,
    GHZCircuitInitialization,
    GroverCircuitInitialization,
    QFTCircuitInitialization,
    AECircuitInitialization,
    QPECircuitInitialization,
    WStateCircuitInitialization,
    HalfAdderCircuitInitialization,
    BVCircuitInitialization,
    GraphStateCircuitInitialization,
)
from qlego_evaluation.adapter.passes import EvaluationPass
from qlego_qiskit.adapter.passes import (
    PresetPasses,
    PresetInitPass,
    PresetLayoutPass,
    PresetRoutingPass,
    PresetTranslationPass,
    PresetOptimizationPass,
)
from qlego_qiskit.adapter.backend import QiskitBackend
from qlego_generator.template import DefaultCompilationTemplate
from qlego.registry import PassRegistry
from qlego_generator.registry import aggregate_from_environment
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENV_CONFIG_PATH = os.path.join(TESTS_DIR, "envs", "env_config.json")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# All circuit families (Shor removed — fixed qubit sizes only, incompatible with sweep)
# Cirq passes removed from all experiments per design decision
ALL_CIRCUITS = [
    DJCircuitInitialization,
    GHZCircuitInitialization,
    GroverCircuitInitialization,
    QFTCircuitInitialization,
    AECircuitInitialization,
    QPECircuitInitialization,
    WStateCircuitInitialization,
    HalfAdderCircuitInitialization,
    BVCircuitInitialization,
    GraphStateCircuitInitialization,
]

# HalfAdder requires odd num_qubits >= 3; use this set for circuits with constraints
HALF_ADDER_QUBITS = [5, 15, 25]

def get_qubits_for_circuit(circuit_cls, qubit_scales):
    """Return valid qubit scales for a given circuit class."""
    if circuit_cls is HalfAdderCircuitInitialization:
        return [q for q in qubit_scales if q in HALF_ADDER_QUBITS]
    return qubit_scales

# Qubit scales
STANDARD_QUBITS = [5, 10, 15, 20]
SCALE_QUBITS = [5, 10, 15, 20, 25, 30]

# Random seeds for stochastic passes
SEEDS = [0, 42, 123]

# Subprocess timeout (5 minutes)
TIMEOUT_SECONDS = 300

# ---------------------------------------------------------------------------
# Timeout patch for subprocess calls
# ---------------------------------------------------------------------------

_original_subprocess_run = subprocess.run

def _subprocess_run_with_timeout(*args, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT_SECONDS)
    try:
        return _original_subprocess_run(*args, **kwargs)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Timeout: pipeline exceeded {TIMEOUT_SECONDS}s") from e

subprocess.run = _subprocess_run_with_timeout

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def initialize_circuit(generator_cls, num_qubits: int) -> str:
    """Generate a circuit as QASM string."""
    pipeline = QPipeline([generator_cls(num_qubits)], env_config_path=ENV_CONFIG_PATH)
    ctx = QPassContext()
    ctx = pipeline.run("", ctx)
    return ctx.qasm


def evaluate(qasm: str) -> dict:
    """Evaluate a compiled circuit and return metrics dict."""
    pipeline = QPipeline([EvaluationPass()], env_config_path=ENV_CONFIG_PATH)
    ctx = QPassContext(qasm=qasm)
    ctx = pipeline.run("", ctx)
    return ctx.metadata["evaluation_metrics"]


def get_heavy_hex_backend():
    """Return FakeBrooklyn heavy-hex backend and its JSON representation."""
    backend = FakeBrooklynV2()
    backend_json = QiskitBackend.from_qiskit(backend).to_json()
    return backend, backend_json


def get_all_to_all_backend(n_qubits: int):
    """Return a fully-connected all-to-all backend JSON for n qubits."""
    edges = []
    for i in range(n_qubits):
        for j in range(i + 1, n_qubits):
            edges.append([i, j])
    backend_json = {
        "n_qubits": n_qubits,
        "edges": edges,
        "basis_gates": ["cx", "id", "rz", "sx", "x"],
    }
    import json
    return json.dumps(backend_json)


def ensure_registry():
    """Ensure all passes are registered from all plugins."""
    aggregate_from_environment(ENV_CONFIG_PATH)


def safe_run_pipeline(template, initial_qasm, backend_json, extra_result=None):
    """
    Run a compilation template safely, returning (metrics_dict, status, error).
    extra_result is an optional dict of fields to include in the result.
    """
    result = dict(extra_result or {})
    try:
        ctx = QPassContext(qasm=initial_qasm, hardware=backend_json)
        compiled_ctx = template.compile(ctx=ctx, env_config_path=ENV_CONFIG_PATH)
        metrics = evaluate(compiled_ctx.qasm)
        result["status"] = "success"
        result["error"] = ""
        result.update(metrics)
    except Exception as e:
        full_error = str(e)
        try:
            lines = [l.strip() for l in full_error.splitlines()
                     if "Error:" in l or "Exception:" in l]
            error_msg = lines[-1] if lines else full_error[:200]
        except IndexError:
            error_msg = full_error[:200]
        result["status"] = "failed"
        result["error"] = error_msg
    return result


def save_results(df: pd.DataFrame, filename: str):
    """Save results DataFrame to the results directory."""
    path = os.path.join(RESULTS_DIR, filename)
    df.to_csv(path, index=False)
    print(f"Saved {path} ({len(df)} rows)")
