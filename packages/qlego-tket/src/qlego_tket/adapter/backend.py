from qlego.qbackend import QBackend


class TketBackend(QBackend):

    @classmethod
    def from_tket(cls, backend) -> "QBackend":
        """
        Extract TKET backend constraints into QBackend:
          - n_qubits from architecture
          - edges from architecture coupling
          - durations (seconds) if available
          - gate_set as strings (your basis names)
        """
        info = backend.backend_info
        arch = info.architecture

        # architecture edges
        edges = set(tuple(e) for e in arch.coupling)

        # n_qubits: tket nodes can be non-contiguous; keep it simple:
        # if you assume nodes are 0..n-1, this works:
        n_qubits = max(max(a, b) for (a, b) in edges) + 1 if edges else arch.n_nodes

        # gate durations: tket uses dict[(OpType, qubits_tuple)] -> float (units depend on backend)
        # Many backends use seconds; if yours uses another unit, you must normalize here.
        durations = {}
        gd = getattr(info, "gate_durations", None) or {}
        for (optype, qbs), t in gd.items():
            name = optype.name.lower()
            durations[(name, tuple(qbs))] = float(t)

        # gate set: OpType -> string names
        gs = getattr(info, "gate_set", None) or set()
        gate_set = {op.name.lower() for op in gs}

        # gate errors: (OpType, qubits_tuple) -> float
        errors = {}
        ge = getattr(info, "all_gate_errors", None) or {}
        for (optype, qbs), e in ge.items():
            name = optype.name.lower()
            errors[(name, tuple(qbs))] = float(e)

        # Always allow measure if you want parity with Qiskit
        gate_set.add("measure")

        return cls(n_qubits, edges, durations, gate_set=gate_set, errors=errors)

    def to_tket_backend_info(self):
        """
        Build a TKET BackendInfo enforcing:
          - architecture from edges
          - supported OpTypes from gate_set (strings)
          - optional gate_durations from durations
        """
        from pytket.architecture import Architecture
        from pytket.backends.backendinfo import BackendInfo
        from pytket.circuit import OpType
        from pytket.unit_id import Node
        # print("No. Of Qubits: ", self.n_qubits)
        # print("Edges:", self.edges)
        # nodes = [Node(i) for i in range(self.n_qubits)]
        # edges = [(Node(a), Node(b)) for (a, b) in self.edges]
        edges = [(int(a), int(b)) for (a, b) in self.edges]
        arch = Architecture(edges)

        # arch = Architecture(edges, nodes=nodes) 

        # --- map your string basis to OpType ---
        # Extend this mapping as needed.
        str_to_optype = {
            "cx": OpType.CX,
            "cz": OpType.CZ,
            "x": OpType.X,
            "sx": OpType.SX,
            "rz": OpType.Rz,
            "h": OpType.H,
            "s": OpType.S,
            "t": OpType.T,
            "swap": OpType.SWAP,
            "measure": OpType.Measure,
            "reset": OpType.Reset,
            # if you use IBM-native: "ecr": OpType.ECR  (check your pytket version)
        }

        gate_set_ops = set()
        for g in self.gate_set:
            op = str_to_optype.get(g.lower())
            if op is not None:
                gate_set_ops.add(op)

        # --- durations: (OpType, qubits_tuple) -> float ---
        gate_durations = {}
        for (gname, qbs), t in self.durations.items():
            op = str_to_optype.get(gname.lower())
            if op is not None:
                gate_durations[(op, tuple(qbs))] = float(t)

        # BackendInfo signature varies slightly by pytket version.
        # The most common fields you can safely provide are name/device_name/version/architecture/gate_set/gate_durations.
        return BackendInfo(
            name="qbackend",
            device_name="qbackend",
            version="1.0",
            architecture=arch,
            gate_set=gate_set_ops,
            # gate_durations=gate_durations,
        )

    def to_tket_backend(self):
        from pytket.backends.backend import Backend

        info = self.to_tket_backend_info()

        class QBackendTKET(Backend):
            @property
            def backend_info(self):
                return info

        return QBackendTKET()