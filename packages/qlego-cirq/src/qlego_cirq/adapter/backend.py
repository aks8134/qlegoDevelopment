from qlego.qbackend import QBackend

def _qubit_key(q):
    try:
        import cirq
        if isinstance(q, cirq.LineQubit):
            return (0, q.x)
        if isinstance(q, cirq.GridQubit):
            return (1, q.row, q.col)
        if isinstance(q, cirq.NamedQubit):
            return (2, q.name)
    except Exception:
        pass
    return (9, repr(q))

class CirqBackend(QBackend):
    
    @classmethod
    def from_cirq_device(cls, device) -> "QBackend":
        # --- qubits ---
        qubits = []
        if hasattr(device, "qubit_set"):
            try:
                qubits = list(device.qubit_set())
            except Exception:
                qubits = []
        if not qubits and hasattr(device, "qubits"):
            try:
                qubits = list(device.qubits)
            except Exception:
                qubits = []

        qubits = sorted(qubits, key=_qubit_key)
        q2i = {q: i for i, q in enumerate(qubits)}
        n_qubits = len(qubits)

        # --- edges: output canonical (min,max) ---
        edges = set()

        # 1) Graph devices (UndirectedGraphDevice exposes .edges)
        if hasattr(device, "edges"):
            try:
                for e in device.edges:
                    e = tuple(e)
                    if len(e) == 2 and e[0] in q2i and e[1] in q2i:
                        a, b = q2i[e[0]], q2i[e[1]]
                        edges.add((a, b) if a < b else (b, a))
            except Exception:
                pass

        # 2) Fallback: metadata-based
        if not edges:
            md = getattr(device, "metadata", None)
            if md is not None:
                pairs = getattr(md, "qubit_pairs", None)
                if pairs is not None:
                    for qa, qb in pairs:
                        if qa in q2i and qb in q2i:
                            a, b = q2i[qa], q2i[qb]
                            edges.add((a, b) if a < b else (b, a))
                else:
                    g = getattr(md, "nx_graph", None) or getattr(md, "graph", None)
                    if g is not None:
                        try:
                            for qa, qb in g.edges:
                                if qa in q2i and qb in q2i:
                                    a, b = q2i[qa], q2i[qb]
                                    edges.add((a, b) if a < b else (b, a))
                        except Exception:
                            pass

        return cls(n_qubits, edges, gate_durations={}, gate_set=set(), errors={})
    
    def to_cirq_device(self):
        import cirq
        import networkx as nx
        from cirq.contrib.graph_device import UndirectedGraphDevice, UndirectedHypergraph

        qs = list(cirq.LineQubit.range(self.n_qubits))

        g = nx.Graph()
        g.add_nodes_from(qs)

        # self.edges already contains canonical undirected pairs (a < b)
        for a, b in (self.edges or set()):
            g.add_edge(qs[int(a)], qs[int(b)])

        return UndirectedGraphDevice(device_graph=UndirectedHypergraph(g))


    def to_cirq_sampler(self):
        """
        Return a Cirq sampler (Simulator) that can be used for execution/sampling.
        """
        import cirq
        return cirq.Simulator()
