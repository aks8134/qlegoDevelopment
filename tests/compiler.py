from qlego_qiskit.adapter.passes import QiskitPass
from qlego.qpass import QPipeline, QPassContext
# from qiskit.transpiler import CouplingMap
from tests.qiskit_helper import *
from tests.tket_helper import *
from qlego_evaluation.adapter.passes import EvaluationPass
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego_qiskit.adapter.backend import QiskitBackend
from tests.bqskit_helper import *
from tests.mqt_helper import DJCircuitInitialization
from qlego_mqt_verification.adapter.passes import MQTVerficiation
from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS
from qiskit import QuantumCircuit
backend = FakeBrooklynV2()
backend = QiskitBackend.from_qiskit(backend).to_json()
def build_toolcentric_qpipeline(
    coupling_map,
    basis_gates,
    *,
    optimization_level: int = 2,
    seed: int | None = 0,
    instruction_durations=None,
):
    # lp = LayoutPass( optimization_level)
    # print(lp.c_name())
    return QPipeline([
        # InitStage(),
        # lp,
        DJCircuitInitialization(),
        # BqskitInit(),
        # BqskitTranslation(),
        # BqskitOptimisePass(level=1),
        # BqskitPlacement(),
        # BqskitRouting(),
        # TranspileStage(),
        InitStage(),
        # TketInit(),
        # TketPlacement(),
        DefaultLayoutPass(),
        # # TketInit(),
        # # TketPlacement(),
        # # TkETOptimisePass(level = optimization_level),
        RoutingStage(),
        # TketRouting(),
        # BqskitTranslation(),
        TranslationStage(),
        OptimizationStage(),
        # TkETOptimisePass(level = optimization_level),
        # TketTranslation(),
        SchedulingStage(),
        EvaluationPass(),
        MQTVerficiation(),
    ])

cm = []

pipeline = build_toolcentric_qpipeline(
    coupling_map=cm,
    basis_gates=["rz", "sx", "x", "cx", "measure"],
    optimization_level=2,
    seed=42,
)

ctx = QPassContext(
    hardware=backend
)

out_ctx = pipeline.run("", ctx)
final_qasm = out_ctx.qasm
eval_metrics = out_ctx.metadata
print(final_qasm)
qc = loads(final_qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
# print(qc)
print("Evaluation Metrics")
print(eval_metrics)
# print("Coupling Map Edges")
# print(QBackend.from_json(backend).edges)