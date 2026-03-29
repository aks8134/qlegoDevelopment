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
#     Convenience wrapper: intended for routing-style passes (SWAP insertion). #     Keeping the same shape as QiskitRoutingPass for symmetry.
#     """
#     name = "cirq_routing_pass"

from qlego.registry import register_pass
class BaseCirqRoutingPass(CirqPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_routing_algo(self, device_graph, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        backend = self.get_compatible_backend(ctx.hardware)
        
        if hasattr(backend, "metadata") and backend.metadata is not None:
            device_graph = backend.metadata.nx_graph
        else:
            # Fallback if the device doesn't have an nx_graph
            import networkx as nx
            device_graph = nx.Graph() 
            
        routing_algo = self.get_routing_algo(device_graph, **self.pass_cfg)
        super().__init__([routing_algo])
        
        ctx = super().run(ctx)
        return ctx

@register_pass("Routing")
class RouteCQCPass(BaseCirqRoutingPass):
    name = "Route CQC"
    def get_routing_algo(self, device_graph, **kwargs):
        from cirq.routing import RouteCQC
        return RouteCQC(device_graph, **kwargs)
class BaseCirqLayoutPass(CirqPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_layout_algo(self, device_graph, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        import cirq
        from cirq.routing import RouteCQC
        backend = self.get_compatible_backend(ctx.hardware)
        
        if hasattr(backend, "metadata") and backend.metadata is not None:
            device_graph = backend.metadata.nx_graph
        else:
            # Fallback if the device doesn't have an nx_graph
            import networkx as nx
            device_graph = nx.Graph() 
        
        initial_mapper = self.get_layout_algo(device_graph, **self.pass_cfg)
        router = RouteCQC(device_graph)
        router.initial_mapper = initial_mapper
        
        super().__init__([router])
        
        # We need to run it natively using super
        ctx = super().run(ctx)
        return ctx

@register_pass("Layout")
class LinePlacementStrategyPass(BaseCirqLayoutPass):
    name = "Line Placement Strategy"
    def get_layout_algo(self, device_graph, **kwargs):
        from cirq.routing import LinePlacementStrategy
        return LinePlacementStrategy(device_graph, **kwargs)

@register_pass("Layout")
class GreedySequenceSearchPass(BaseCirqLayoutPass):
    name = "Greedy Sequence Search"
    def get_layout_algo(self, device_graph, **kwargs):
        from cirq.routing import GreedySequenceSearch
        return GreedySequenceSearch(**kwargs)

@register_pass("Layout")
class AnnealSequenceSearchPass(BaseCirqLayoutPass):
    name = "Anneal Sequence Search"
    def get_layout_algo(self, device_graph, **kwargs):
        from cirq.routing import AnnealSequenceSearch
        return AnnealSequenceSearch(**kwargs)

class BaseCirqOptimizationPass(CirqPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_optimization_algo(self, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        opt_algo = self.get_optimization_algo(**self.pass_cfg)
        super().__init__([opt_algo])
        ctx = super().run(ctx)
        return ctx

@register_pass("Optimization")
class MergeSingleQubitGatesToPhxzPass(BaseCirqOptimizationPass):
    name = "Merge Single Qubit Gates to Phxz"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import merge_single_qubit_gates_to_phxz
        return merge_single_qubit_gates_to_phxz

@register_pass("Optimization")
class MergeSingleQubitGatesPhasedXAndZPass(BaseCirqOptimizationPass):
    name = "Merge Single Qubit Gates Phased X And Z"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import merge_single_qubit_gates_to_phased_x_and_z
        return merge_single_qubit_gates_to_phased_x_and_z

@register_pass("Optimization")
class EjectZPass(BaseCirqOptimizationPass):
    name = "Eject Z"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import EjectZ
        return EjectZ(**kwargs)

@register_pass("Optimization")
class EjectPhasedPaulisPass(BaseCirqOptimizationPass):
    name = "Eject Phased Paulis"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import EjectPhasedPaulis
        return EjectPhasedPaulis(**kwargs)

@register_pass("Optimization")
class MergeKQubitUnitariesPass(BaseCirqOptimizationPass):
    name = "Merge K Qubit Unitaries"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import MergeSingleQubitGates # fallback
        try:
            from cirq.optimizers import merge_k_qubit_unitaries
            return merge_k_qubit_unitaries
        except ImportError:
            # Fallback if specific version doesn't have it
            return MergeSingleQubitGates()

@register_pass("Optimization")
class DropNegligibleOperationsPass(BaseCirqOptimizationPass):
    name = "Drop Negligible Operations"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import DropNegligible
        return DropNegligible(**kwargs)

@register_pass("Optimization")
class DropEmptyMomentsPass(BaseCirqOptimizationPass):
    name = "Drop Empty Moments"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import DropEmptyMoments
        return DropEmptyMoments(**kwargs)

@register_pass("Optimization")
class DeferMeasurementsPass(BaseCirqOptimizationPass):
    name = "Defer Measurements"
    def get_optimization_algo(self, **kwargs):
        import cirq
        return cirq.defer_measurements

@register_pass("Optimization")
class OptimizeForTargetGatesetPass(BaseCirqOptimizationPass):
    name = "Optimize For Target Gateset"
    def get_optimization_algo(self, **kwargs):
        from cirq.optimizers import OptimizeForTargetGateset
        # This typically requires a gateset instance. We return the class wrapper if missing
        # but optimally kwargs MUST provide a `gateset`
        return OptimizeForTargetGateset(**kwargs)

@register_pass("Optimization")
class AlignLeftPass(BaseCirqOptimizationPass):
    name = "Align Left"
    def get_optimization_algo(self, **kwargs):
        import cirq
        from cirq.circuits.insert_strategy import InsertStrategy
        def align_left(circuit):
            return cirq.align_left(circuit)
        # Note: Cirq passes expect `__call__` or `optimize_circuit`
        return align_left

@register_pass("Optimization")
class AlignRightPass(BaseCirqOptimizationPass):
    name = "Align Right"
    def get_optimization_algo(self, **kwargs):
        import cirq
        def align_right(circuit):
            return cirq.align_right(circuit)
        return align_right

@register_pass("Optimization")
class StratifiedCircuitPass(BaseCirqOptimizationPass):
    name = "Stratified Circuit"
    def get_optimization_algo(self, **kwargs):
        from cirq.circuits import stratified_circuit
        def stratify(circuit):
            return stratified_circuit(circuit, **kwargs)
        return stratify
