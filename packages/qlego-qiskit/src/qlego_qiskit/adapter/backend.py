from qlego.qbackend import QBackend

class QiskitBackend(QBackend):
    @classmethod
    def from_qiskit(cls, backend) -> "QBackend":
        n_qubits = backend.configuration().num_qubits

        coupling = getattr(backend, "coupling_map", None)
        edges = set(coupling.get_edges()) if coupling is not None else set()

        durations_obj = backend.instruction_durations
        dt = getattr(backend, "dt", None)

        # gate_set as basis_gates strings
        gate_set = []
        tgt = getattr(backend, "target", None)
        if tgt is not None:
            gate_set.extend([n.lower() for n in tgt.operation_names if n.lower() not in gate_set])
        else:
            gate_set.extend([n.lower() for n in (backend.configuration().basis_gates or []) if n.lower() not in gate_set])

        if "measure" not in gate_set:
            gate_set.append("measure")

        # durations in seconds: iterate qargs from Target (stable)
        gate_durations = {}
        gate_errors = {}
        if tgt is not None:
            for opname in tgt.operation_names:
                if opname == "delay":
                    continue
                for qargs in tgt.qargs_for_operation_name(opname):
                    props = tgt[opname].get(qargs)
                    if props is None:
                        continue
                    # duration
                    if dt is not None and props.duration is not None:
                        gate_durations[(opname, tuple(qargs))] = float(props.duration)
                    # error
                    if props.error is not None:
                        gate_errors[(opname, tuple(qargs))] = float(props.error)

        # Fallback if target isn't available: just keep durations/errors empty (still usable)
        return cls(n_qubits, edges, gate_durations, gate_set=gate_set, errors=gate_errors)

    def to_qiskit_target(self):
        """
        Build a Qiskit Target from:
        - self.gate_set (basis gate names, strings)
        - self.edges (coupling)
        - self.durations (seconds, optional)
        """
        from qiskit.transpiler.target import Target, InstructionProperties
        from qiskit.transpiler import CouplingMap

        from qiskit.circuit.library.standard_gates import XGate, SXGate, RZGate, CXGate, CZGate, IGate
        from qiskit.circuit import Measure, Reset, Delay, Parameter

        name_to_inst = {
            "x": XGate(),
            "sx": SXGate(),
            "rz": RZGate(Parameter("theta")),
            "cx": CXGate(),
            "cz": CZGate(),
            "id": IGate(),
            "measure": Measure(),
            "reset": Reset(),
            "delay": Delay(Parameter("t")),
            # add "ecr": ECRGate() etc if you include it in gate_set
        }

        tgt = Target(num_qubits=self.n_qubits)
        cm = CouplingMap(list(self.edges))
        # Keep original order if gate_set is a list
        basis = []
        for g in (self.gate_set or []):
            if g.lower() not in basis:
                basis.append(g.lower())

        def dur(name: str, qargs: tuple[int, ...]):
            return self.durations.get((name, qargs))

        def err(name: str, qargs: tuple[int, ...]):
            return self.errors.get((name, qargs))

        # ---- 1q instructions: add ONCE with all (q,) keys ----
        for gname in basis:
            inst = name_to_inst.get(gname)
            if inst is None or inst.num_qubits != 1:
                continue

            props = {}
            for q in range(self.n_qubits):
                props[(q,)] = InstructionProperties(duration=dur(gname, (q,)), error=err(gname, (q,)))
            tgt.add_instruction(inst, props)

        # ---- 2q instructions: add ONCE with all (a,b) keys ----
        for gname in basis:
            inst = name_to_inst.get(gname)
            if inst is None or inst.num_qubits != 2:
                continue

            props = {}
            for a, b in cm.get_edges():
                props[(a, b)] = InstructionProperties(duration=dur(gname, (a, b)), error=err(gname, (a, b)))
            if props:  # only add if there is at least one allowed edge
                tgt.add_instruction(inst, props)

        return tgt

    
    def to_qiskit_backend(self):
        """
        Return a Qiskit backend that carries your Target (basis + coupling + durations).

        Practical choice: AerSimulator, because it's a real backend you can execute on.
        Use transpile(..., backend=returned_backend) or transpile(..., target=returned_backend.target).
        """
        from qiskit_aer import AerSimulator

        tgt = self.to_qiskit_target()

        # AerSimulator supports setting a target in recent Qiskit/Aer versions.
        # If your version doesn't accept target=, fallback to setting attribute.
        try:
            return AerSimulator(target=tgt)
        except TypeError:
            sim = AerSimulator()
            sim._target = tgt
            return sim