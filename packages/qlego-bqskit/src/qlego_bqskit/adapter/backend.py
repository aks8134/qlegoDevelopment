from qlego.qbackend import QBackend
class BQSKITBackend(QBackend):
    @classmethod
    def from_bqskit(cls, model) -> "QBackend":
        """
        Best-effort extraction from a BQSKit MachineModel into the generic QBackend schema:
          - n_qubits: model.num_qudits
          - edges: model.coupling_graph (undirected edge set)
          - gate_set: best-effort from model.gate_set (names)
          - durations: left empty (BQSKit doesn't standardize gate timing here)
        """
        from bqskit.compiler import MachineModel

        if not isinstance(model, MachineModel):
            raise TypeError("from_bqskit expects a bqskit.compiler.MachineModel")

        n_qubits = int(getattr(model, "num_qudits", getattr(model, "num_qubits", 0)))

        # coupling_graph is an undirected edge set; None => all-to-all in BQSKit
        edges = set()
        cg = getattr(model, "coupling_graph", None)
        if cg is not None:
            if hasattr(cg, "edges"):
                edges = {tuple(e) for e in cg.edges}
            else:
                edges = {tuple(e) for e in cg}

        # gate_set (best-effort stringify)
        gate_set = set()
        gs = getattr(model, "gate_set", None)
        if gs is not None:
            try:
                for g in gs:
                    nm = getattr(g, "qasm_name", None) or getattr(g, "name", None) or g.__class__.__name__
                    if nm is not None:
                        gate_set.add(str(nm).lower())
            except TypeError:
                pass

        return cls(n_qubits, edges, {}, gate_set=gate_set or None, errors={})

    def to_bqskit_machine_model(self):
        """
        Build a BQSKit MachineModel from:
        - self.n_qubits
        - self.edges (undirected edge set)
        - self.gate_set (converted into a BQSKit GateSet)
        """
        from bqskit.compiler import MachineModel, GateSet
        from bqskit.ir.gate import Gate

        # Built-in gate library: bqskit.ir.gates (see IR gate list). 
        # GateSet expects an iterable of Gate objects.  :contentReference[oaicite:0]{index=0}
        from bqskit.ir.gates import (
            IdentityGate,
            XGate, YGate, ZGate, HGate,
            SGate, SdgGate, TGate, TdgGate,
            SXGate, 
            SwapGate, ISwapGate, ECRGate,
            CNOTGate, CZGate, CYGate, CHGate,
            RXGate, RYGate, RZGate,
            CRXGate, CRYGate, CRZGate,
            U1Gate, U2Gate, U3Gate,
            CPGate,
            RXXGate, RYYGate, RZZGate,
            XXGate, YYGate, ZZGate,
        )

        def _gate_from_name(nm: str) -> Gate:
            k = nm.strip().lower()

            # common aliases / qasm names
            if k in {"id", "i"}:
                return IdentityGate()

            if k in {"x"}:
                return XGate()
            if k in {"y"}:
                return YGate()
            if k in {"z"}:
                return ZGate()
            if k in {"h"}:
                return HGate()

            if k in {"s"}:
                return SGate()
            if k in {"sdg"}:
                return SdgGate()
            if k in {"t"}:
                return TGate()
            if k in {"tdg"}:
                return TdgGate()

            if k in {"sx"}:
                return SXGate()
            # if k in {"sxdg"}:
            #     return SXdgGate()

            if k in {"swap"}:
                return SwapGate()
            if k in {"iswap"}:
                return ISwapGate()
            if k in {"ecr"}:
                return ECRGate()

            if k in {"cx", "cnot"}:
                return CNOTGate()
            if k in {"cz"}:
                return CZGate()
            if k in {"cy"}:
                return CYGate()
            if k in {"ch"}:
                return CHGate()

            if k in {"rx"}:
                return RXGate()
            if k in {"ry"}:
                return RYGate()
            if k in {"rz"}:
                return RZGate()

            if k in {"crx"}:
                return CRXGate()
            if k in {"cry"}:
                return CRYGate()
            if k in {"crz"}:
                return CRZGate()

            # OpenQASM2 common phase gate aliases: p == u1
            if k in {"p", "u1"}:
                return U1Gate()
            if k in {"u2"}:
                return U2Gate()
            if k in {"u3", "u"}:
                return U3Gate()

            if k in {"cp"}:
                return CPGate()

            if k in {"rxx"}:
                return RXXGate()
            if k in {"ryy"}:
                return RYYGate()
            if k in {"rzz"}:
                return RZZGate()

            if k in {"xx"}:
                return XXGate()
            if k in {"yy"}:
                return YYGate()
            if k in {"zz"}:
                return ZZGate()

            raise ValueError(f"Unsupported gate in gate_set: {nm!r}")
            # return nm

        # --- convert self.gate_set -> GateSet ---
        gs = getattr(self, "gate_set", None)
        if gs is None:
            raise ValueError("self.gate_set is required for to_bqskit_machine_model().")

        # If already GateSetLike (Gate or iterable of Gate), normalize into GateSet anyway.
        gates = []
        if isinstance(gs, Gate):
            gates = [gs]
        else:
            try:
                for g in gs:
                    if isinstance(g, Gate):
                        gates.append(g)
                    elif isinstance(g, str):
                        if( g in {"delay", "measure", "measure2", "reset"}):
                            continue
                        gates.append(_gate_from_name(g))
                    else:
                        raise TypeError(f"gate_set element must be str or bqskit.ir.gate.Gate, got {type(g)}")
            except TypeError:
                # not iterable
                raise TypeError(f"gate_set must be a Gate, or iterable of (str|Gate); got {type(gs)}")

        gate_set = GateSet(gates)

        # coupling_graph is an undirected edge set; None => all-to-all. :contentReference[oaicite:1]{index=1}
        coupling_graph = [(a,b) for a, b in self.edges ]if (self.edges and len(self.edges) > 0) else None
        
        # MachineModel accepts GateSetLike; we pass a concrete GateSet. :contentReference[oaicite:2]{index=2}
        return MachineModel(self.n_qubits, coupling_graph=coupling_graph, gate_set=gate_set)

