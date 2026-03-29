from qiskit_ibm_runtime.fake_provider import FakeBrooklynV2
from qlego_qiskit.adapter.backend import QiskitBackend

backend = FakeBrooklynV2()
qb_json = QiskitBackend.from_qiskit(backend).to_json()
backend2 = QiskitBackend.from_json(qb_json).to_qiskit_backend()

tgt1 = backend.target
tgt2 = backend2.target

with open("/tmp/tgt1.txt", "w") as f1, open("/tmp/tgt2.txt", "w") as f2:
    for name in sorted(tgt1.operation_names):
        f1.write(f"GATE: {name}\n")
        f2.write(f"GATE: {name}\n")
        if name not in tgt2.operation_names: continue
        qargs = sorted(tgt1.qargs_for_operation_name(name))
        for q in qargs:
            p1 = tgt1[name].get(q)
            p2 = tgt2[name].get(q)
            f1.write(f"  {q}: dur={getattr(p1, 'duration', None)} err={getattr(p1, 'error', None)}\n")
            f2.write(f"  {q}: dur={getattr(p2, 'duration', None)} err={getattr(p2, 'error', None)}\n")
