import json
from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego_qiskit.adapter.backend import QiskitBackend

backend = FakeBrooklynV2()
backend_json = QiskitBackend.from_qiskit(backend).to_json()

with open("backend.json", "w") as f:
    f.write(backend_json)
print("Dumped backend.json")
