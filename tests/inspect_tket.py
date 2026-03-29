from qiskit import QuantumCircuit
from qiskit.providers.fake_provider import GenericBackendV2
from pytket.extensions.qiskit import qiskit_to_tk
from pytket.placement import LinePlacement
from pytket.qasm import circuit_to_qasm_str
from pytket.architecture import Architecture

backend = GenericBackendV2(num_qubits=65)

# DJ circuit 10 qubits has a star topology
qc_dj = QuantumCircuit(10)
qc_dj.h(range(10))
for i in range(9):
    qc_dj.cx(i, 9)

tk_dj = qiskit_to_tk(qc_dj)
print("TKet DJ original qubits:", len(tk_dj.qubits))

edges = list(backend.target.build_coupling_map().get_edges())
arch = Architecture(edges)

# Apply placement
placement_algo = LinePlacement(arch)
placement_map = placement_algo.get_placement_map(tk_dj)
print("DJ placement map length:", len(placement_map))
print("DJ placement map:", placement_map)

tk_dj.rename_units(placement_map)
for n in arch.nodes:
    if n not in tk_dj.qubits:
        tk_dj.add_qubit(n)

print("TKet DJ total qubits after adding architecture nodes:", len(tk_dj.qubits))
qasm_str = circuit_to_qasm_str(tk_dj, header="qelib1")
# print(qasm_str)

import qiskit.qasm2
parsed = qiskit.qasm2.loads(qasm_str)
print("Parsed Qiskit DAG qubits:", len(parsed.qubits))
