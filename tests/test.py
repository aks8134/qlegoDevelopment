from qiskit import QuantumCircuit
import matplotlib.pyplot as plt

qc = QuantumCircuit(3)
for i in range(3):
    qc.x(i)

qc.draw( "mpl" )
plt.show()

