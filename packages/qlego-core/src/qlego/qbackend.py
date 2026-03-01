import json

class QBackend:
    def __init__(self, n_qubits, edges, durations, gate_set=None, errors=None):
        self.n_qubits = n_qubits
        self.edges = edges
        self.durations = durations            # (name, qargs)-> seconds
        self.gate_set = gate_set or [] # set[str] of Qiskit basis gate names
        self.errors = errors or {}            # (name, qargs)-> error rate (float)

    def to_json(self) -> str:
        return json.dumps({
            "n_qubits": self.n_qubits,
            "edges": list(self.edges),
            "durations": {f"{k[0]}:{','.join(map(str,k[1]))}": v for k, v in self.durations.items()},
            "gate_set": sorted(self.gate_set),    # list[str]
            "errors": {f"{k[0]}:{','.join(map(str,k[1]))}": v for k, v in self.errors.items()},
        }, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "QBackend":
        data = json.loads(s)
        durations = {}
        for k, v in data["durations"].items():
            gname, qlist = k.split(":")
            qubits = tuple(map(int, qlist.split(",")))
            durations[(gname, qubits)] = v
        errors = {}
        for k, v in data.get("errors", {}).items():
            gname, qlist = k.split(":")
            qubits = tuple(map(int, qlist.split(",")))
            errors[(gname, qubits)] = v
        return cls(data["n_qubits"], data["edges"], durations, gate_set=data.get("gate_set", []), errors=errors)


    










# import json
# from typing import Optional, Union, Iterable
# from bqskit.ir.machine import MachineModel
# from bqskit.ir.gates import CNOTGate, PhasedXZGate
# from bqskit.ir.gatesets import GateSet, QFASTGateSet

# try:
#     from qiskit.transpiler import CouplingMap, InstructionDurations, Target
#     from qiskit.providers import BackendV2
#     from qiskit.transpiler import InstructionDurations
#     from qiskit.transpiler.target import Target
# except ImportError:
#     BackendV2 = CouplingMap = InstructionDurations = Target = object

# try:
#     from pytket.architecture import Architecture
#     from pytket.backends.backendinfo import BackendInfo
#     from pytket.backends.backend import Backend as TKETBackend
# except ImportError:
#     TKETBackend = Architecture = BackendInfo = object

# try:
#     import cirq
#     from cirq.devices import GridQubit
# except ImportError:
#     cirq = GridQubit = object


# class QBackend:
#     def __init__(
#         self,
#         n_qubits: int,
#         edges: Iterable[tuple[int, int]],
#         durations: dict[tuple[str, tuple[int, ...]], float],
#         gate_set: Optional[GateSet] = None,
#     ):
#         self.n_qubits = n_qubits
#         self.edges = set(edges)
#         self.durations = durations  # gate name + qubits -> duration (sec)
#         self.gate_set = gate_set or QFASTGateSet()

#     # ==== FROM methods ====

#     @classmethod
#     def from_qiskit(cls, backend: BackendV2) -> 'QBackend':
#         target = backend.target
#         coupling = backend.coupling_map
#         durations = backend.instruction_durations()
#         dt = backend.dt
#         n_qubits = backend.configuration().num_qubits
#         edges = coupling.get_edges()

#         gate_durations = {
#             (gate, tuple(qbs)): durations.get(gate, qbs) * dt
#             for gate, qbs in durations.instructions
#         }
#         return cls(n_qubits, edges, gate_durations)

#     @classmethod
#     def from_tket(cls, backend: TKETBackend) -> 'QBackend':
#         info = backend.backend_info
#         arch = info.architecture
#         n_qubits = max(max(pair) for pair in arch.coupling) + 1
#         edges = arch.coupling

#         gate_durations = {
#             (op.name, tuple(qbs)): dur
#             for (op, qbs), dur in info.gate_durations.items()
#         }
#         return cls(n_qubits, edges, gate_durations)

#     @classmethod
#     def from_cirq(cls, device: cirq.Device) -> 'QBackend':
#         qubits = list(device.qubit_set())
#         qmap = {q: i for i, q in enumerate(sorted(qubits))}
#         n_qubits = len(qmap)
#         edges = {(qmap[q1], qmap[q2]) for q1, q2 in device.metadata.qubit_pairs}
#         gate_durations = {}

#         if hasattr(device, "duration_of"):
#             for q in qmap:
#                 try:
#                     gate_durations[("x", (qmap[q],))] = device.duration_of(cirq.X(q)).total_seconds()
#                 except: pass
#             for q1, q2 in edges:
#                 try:
#                     q1_, q2_ = list(qmap.keys())[q1], list(qmap.keys())[q2]
#                     gate_durations[("cz", (q1, q2))] = device.duration_of(cirq.CZ(q1_, q2_)).total_seconds()
#                 except: pass

#         return cls(n_qubits, edges, gate_durations)

#     @classmethod
#     def from_bqskit_machine_model(cls, model: MachineModel) -> 'QBackend':
#         n_qubits = model.num_qudits
#         edges = model.connectivity
#         durations = {
#             (g.label, q): t for (g, q), t in model.gate_durations.items()
#         }
#         return cls(n_qubits, edges, durations, gate_set=model.gate_set)

#     # ==== TO methods ====

#     def to_bqskit_machine_model(self) -> MachineModel:
#         model = MachineModel(self.n_qubits, gate_set=self.gate_set)
#         for src, tgt in self.edges:
#             model.connect(src, tgt)

#         for gate in self.gate_set.gates:
#             if isinstance(gate, CNOTGate):
#                 for src, tgt in self.edges:
#                     dur = self.durations.get(("cx", (src, tgt))) or self.durations.get(("cz", (src, tgt)))
#                     if dur:
#                         model.gate_durations[(gate, (src, tgt))] = dur
#             elif isinstance(gate, PhasedXZGate):
#                 for q in range(self.n_qubits):
#                     for name in ("rz", "x", "u1"):
#                         dur = self.durations.get((name, (q,)))
#                         if dur:
#                             model.gate_durations[(gate, (q,))] = dur
#                             break
#         return model

#     # ==== Serialization ====

#     def to_json(self) -> str:
#         return json.dumps({
#             "n_qubits": self.n_qubits,
#             "edges": list(self.edges),
#             "durations": {f"{k[0]}:{','.join(map(str,k[1]))}": v for k, v in self.durations.items()},
#             "gate_set": [g.label for g in self.gate_set.gates],
#         }, indent=2)

#     @classmethod
#     def from_json(cls, s: str) -> 'QBackend':
#         data = json.loads(s)
#         durations = {}
#         for k, v in data["durations"].items():
#             gname, qlist = k.split(":")
#             qubits = tuple(map(int, qlist.split(",")))
#             durations[(gname, qubits)] = v
#         return cls(data["n_qubits"], data["edges"], durations)
