from qiskit import QuantumCircuit
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import SabreLayout
from qiskit.providers.fake_provider import GenericBackendV2

qc = QuantumCircuit(5)
qc.h(0)
qc.cx(0, 1)

backend = GenericBackendV2(num_qubits=65)

pm = PassManager()
pm.append(SabreLayout(backend.target))

# Let's inspect what SabreLayout does!
try:
    final_circ = pm.run(qc)
    print("SabreLayout succeeded without ApplyLayout!")
    layout = pm.property_set['layout']
    print(layout)
    virtuals = layout.get_virtual_bits()
    print("Virtual bits in layout:")
    for v in virtuals:
        print(v, "id=", id(v))
    
    print("\nQubits in final_circ:")
    for q in final_circ.qubits:
        print(q, "id=", id(q))
        
    print("\nQubits in original_qubit_indices:")
    orig = pm.property_set.get('original_qubit_indices', {})
    for q in orig:
        print(q, "id=", id(q))
except Exception as e:
    import traceback
    traceback.print_exc()

