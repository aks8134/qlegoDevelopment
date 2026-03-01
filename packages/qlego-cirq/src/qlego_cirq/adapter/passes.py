import os
from qlego.qpass import QPass, QPassContext
from qlego_cirq.adapter.backend import CirqBackend, QBackend


class CirqPass(QPass):
    name = "cirq_pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))

    def __init__(self, cirq_passes):
        # cirq_passes: list of optimizers/transformers/callables
        self.cirq_passes = cirq_passes

    def get_compatible_backend(self, backend):
        import cirq

        if isinstance(backend, cirq.Device):
            return backend
        if isinstance(backend, cirq.Sampler):
            return backend
        if isinstance(backend, QBackend):
            return backend.to_cirq_device()
        if isinstance(backend, str):
            backend = CirqBackend.from_json(backend)
            return backend.to_cirq_device()
        else:
            raise TypeError()

    def run(self, ctx: QPassContext) -> QPassContext:
        import cirq
        from cirq.contrib.qasm_import import circuit_from_qasm

        circuit = circuit_from_qasm(ctx.qasm)

        for p in self.cirq_passes:
            # 1) Cirq optimizers (in-place)
            opt = getattr(p, "optimize_circuit", None)
            if callable(opt):
                opt(circuit)
                continue

            # 2) Cirq transformers/callables (return a circuit)
            if callable(p):
                out = p(circuit)
                if out is not None:
                    circuit = out
                continue

            raise TypeError(f"Incompatible Cirq pass: {type(p)}")

        ctx.qasm = cirq.qasm(circuit)
        return ctx


# class CirqRoutingPass(CirqPass):
#     """
#     Convenience wrapper: intended for routing-style passes (SWAP insertion).
#     Keeping the same shape as QiskitRoutingPass for symmetry.
#     """
#     name = "cirq_routing_pass"
