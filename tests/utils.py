from qiskit.transpiler import generate_preset_pass_manager
# from tests.qiskit_helper import TranspileStage
from qlego.qpass import QPipeline, QPassContext
from qlego_mqt_workload.adapter.passes import * 
from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego_evaluation.adapter.passes import EvaluationPass
from qlego_qiskit.adapter.backend import QiskitBackend
import pandas as pd
from qlego_qiskit.adapter.passes import PresetPasses, PresetInitPass, PresetLayoutPass, PresetRoutingPass, PresetTranslationPass, PresetOptimizationPass, PresetSchedulingPass
from qlego_mqt_verification.adapter.passes import MQTVerification

def initialize_circuit(generator,num_qubits):
    pipeline = QPipeline([
        generator(num_qubits),
    ])
    ctx = QPassContext()
    ctx = pipeline.run("",ctx)
    return ctx.qasm

def evaluation_metrics(qc, initial_qasm):
    pipeline = QPipeline([EvaluationPass()])
    ctx = QPassContext(qasm=qc, metadata={"initial_qasm": initial_qasm})
    ctx = pipeline.run("", ctx)
    return ctx.metadata["evaluation_metrics"]


def qiskit_compile(qc, optimization_level, backend, add_verification = False):
    from qlego_qiskit.adapter.passes import _extract_layouts_from_property_set
    initial_qc = qc
    qc = loads(qc, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
    pm = generate_preset_pass_manager(optimization_level=optimization_level, backend=backend, seed_transpiler = 0)
    final_circ = pm.run(qc)
    qc_str = dumps(final_circ)  
    if( add_verification ):
        backend_json = QiskitBackend.from_qiskit(backend).to_json()
        init_layout, final_layout = _extract_layouts_from_property_set(pm.property_set, qc, final_circ)
        meta = {"initial_qasm": initial_qc}
        if init_layout is not None:
            meta["layout"] = {"initial": init_layout, "final": final_layout}
        passes = [MQTVerification()]
        pipeline = QPipeline(passes)
        ctx = QPassContext(qasm=qc_str, hardware=backend_json, metadata=meta)
        ctx = pipeline.run("",ctx)
        return qc_str, "qiskit", ctx.metadata
    else:
        return qc_str, "qiskit"


def qlego_qiskit_compile(qc, optimization_level, backend, add_verification = False):
    backend = QiskitBackend.from_qiskit(backend).to_json()
    passes = [PresetPasses(optimization_level=optimization_level)]
    if( add_verification ):
        passes.append(MQTVerification())
    pipeline = QPipeline(passes)
    ctx = QPassContext(qasm=qc, hardware=backend, metadata={"initial_qasm": qc})
    ctx = pipeline.run("",ctx)
    if( add_verification ):
        return ctx.qasm, "qlego_qiskit", ctx.metadata
    else:
        return ctx.qasm, "qlego_qiskit"

def qlego_qiskit_compose_compile(qc, optimization_level, backend, add_verification = False):
    backend = QiskitBackend.from_qiskit(backend).to_json()
    passes = [
        PresetInitPass(optimization_level=optimization_level),
        PresetLayoutPass(optimization_level=optimization_level),
        PresetRoutingPass(optimization_level=optimization_level),
        PresetTranslationPass(optimization_level=optimization_level),
        PresetOptimizationPass(optimization_level=optimization_level),
        PresetSchedulingPass(optimization_level=optimization_level),
    ]
    if( add_verification ):
        passes.append(MQTVerification())
    pipeline = QPipeline(passes)
    ctx = QPassContext(qasm=qc, hardware=backend, metadata={"initial_qasm": qc})
    ctx = pipeline.run("",ctx)
    if( add_verification ):
        return ctx.qasm, "qlego_qiskit_compose", ctx.metadata
    else:
        return ctx.qasm, "qlego_qiskit_compose"