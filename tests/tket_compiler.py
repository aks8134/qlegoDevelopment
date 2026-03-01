from qiskit import QuantumCircuit


from qiskit import QuantumCircuit
from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS

circ = QuantumCircuit(3)
circ.x(2)
circ.h(range(3))
circ.ccx(0, 1, 2)
circ.h(range(2))
circ.x(range(2))
circ.h(1)
circ.cx(0, 1)
circ.h(1)
circ.x(range(2))
circ.h(range(2))
circ.measure_all()
# circ.draw(output="mpl", style="iqp")
circ1 = dumps(circ)
circ1 = loads(circ1, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
from qiskit import transpile
from qiskit.providers.fake_provider import GenericBackendV2

# define the target architecture
backend = GenericBackendV2(num_qubits=5, coupling_map=[[0, 1], [1, 0], [1, 2], [2, 1], [1, 3], [3, 1], [3, 4], [4, 3]])

# compile circuit to the target architecture
optimization_level = 1
circ_comp = transpile(circ, backend=backend, optimization_level=optimization_level)
circ2 = dumps(circ_comp)
circ2 = loads(circ2, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
from mqt.qcec import verify, verify_compilation
import json
# circ1 = loads(json.load(open("temp_initial_circ.json", "r")), custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS )
# circ2 = loads( json.load(open("temp_final_circ.json", "r")), custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS )


# results = verify(circ1, circ2, 
#                 #  check_partial_equivalence=True, 
#                 #  backpropagate_output_permutation=True
#                  )
# print(str(results.equivalence))

q1 = json.load(open("temp_initial_circ.json"))
q2 = json.load(open("temp_final_circ.json"))
# print(q1)
# q1 = q1.replace("creg c[4];", "creg c[5];") + "\nmeasure q[4] -> c[4];\n"
# q2 = q2.replace("creg c[4];", "creg c[5];") + "\nmeasure q[8] -> c[4];\n"
from qiskit.quantum_info import Operator
circ1 = loads(q1, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
circ2 = loads(q2, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)


# results = verify_compilation(circ1, circ2,
#                             check_partial_equivalence=True, 
#                             backpropagate_output_permutation=True,
#                             transform_dynamic_circuit = True
#                             )
# print(results.equivalence)

# results = verify(circ, circ2,  check_partial_equivalence=True, backpropagate_output_permutation=True)
# print(str(results.equivalence))