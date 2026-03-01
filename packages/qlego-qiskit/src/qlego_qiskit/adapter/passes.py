import os
from qlego.qpass import QPass, QPassContext 
import subprocess
import json
from .backend import QiskitBackend, QBackend

def _extract_layouts_from_property_set(ps, qc):
    """
    Return (current_layout, final_layout) as lists where:
      layout[i] = physical_qubit_index assigned to logical qubit i
    """
    # Preferred: TranspileLayout has both initial and final permutations
    tl = ps.get("transpile_layout", None)
    if tl is not None:
        # In Qiskit, these are index-based layouts (good for serialization)
        current = tl.initial_index_layout(filter_ancillas=True)
        final = tl.final_index_layout(filter_ancillas=True)
        return list(current), list(final)

    # Fallback: sometimes only 'layout' is present (pre-routing)
    layout = ps.get("layout", None)
    if layout is not None:
        # layout maps Qubit objects -> physical indices
        current = [layout[q] for q in qc.qubits]
        # no routing info => final unknown; treat as current
        return list(current), list(current)

    return None, None

class QiskitPass(QPass):
    name = "qiskit_pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, qiskit_passes):
        self.qiskit_passes = qiskit_passes

    def get_compatible_backend(self, backend):
        from qiskit.providers import Backend
        if( isinstance(backend, Backend)):
            return backend
        elif(isinstance(backend, QBackend)):
            return backend.to_qiskit_backend()
        elif(isinstance(backend, str)):
            backend = QiskitBackend.from_json(backend)
            return backend.to_qiskit_backend()
        else:
            raise TypeError("Invalid type of backend given")

    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS # qasm2/qasm3 here
        from qiskit.transpiler import PassManager, PropertySet, Layout
        from qiskit.transpiler.basepasses import BasePass
        from qiskit.passmanager import BasePassManager
        from qiskit.transpiler.passes import SetLayout
        import pickle
        qc = loads(ctx.qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
        pm = PassManager()
        if(ctx.metadata.get("layout_needed", False)):
            current_layout = Layout({qb: i for i, qb in enumerate(qc.qubits)})
            pm.append(SetLayout(current_layout))
        for pass_i in self.qiskit_passes:
            if( isinstance(pass_i, BasePass) ):
                pm.append(pass_i)
            elif( isinstance(pass_i, BasePassManager)):
                pm.append(pass_i.to_flow_controller())
            else:
                raise "Incompatible QiskitPass Encountered; use PassManager or Pass"
            

        final_circ = pm.run(qc)
        ctx.qasm = dumps(final_circ)
        return ctx

    
class QiskitRoutingPass(QiskitPass):
    def run(self, ctx):
        ctx.metadata["layout_needed"] = True
        ctx = super().run(ctx)
        ctx.metadata.pop("layout_needed", None)
        return ctx