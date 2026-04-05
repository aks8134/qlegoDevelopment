import os
from qlego_bqskit.adapter.backend import BQSKITBackend, QBackend
from qlego.qpass import QPass, QPassContext
def _bqskit_circuit_from_qasm_str(qasm: str):
    from bqskit import Circuit
    import tempfile, os
    import re
    
    # Remove measurements and classical registers for BQSKit processing
    # They'll be restored later or added back at the end of the pipeline
    qasm_no_measurements = re.sub(r'creg\s+\w+\[\d+\];', '', qasm)
    qasm_no_measurements = re.sub(r'measure\s+\w+\[\d+\]\s*->\s*\w+\[\d+\];', '', qasm_no_measurements)
    qasm_no_measurements = re.sub(r'barrier[^;]*;', '', qasm_no_measurements)  # Also remove barriers
    
    f = tempfile.NamedTemporaryFile("w", suffix=".qasm", delete=False)
    try:
        f.write(qasm_no_measurements)
        f.close()
        return Circuit.from_file(f.name)
    finally:
        try:
            os.remove(f.name)
        except OSError:
            pass


# In _bqskit_circuit_to_qasm_str
def _bqskit_circuit_to_qasm_str(circ):
    import tempfile, os

    # Unfold any circuitgate_XXXX composite gates back to primitives before
    # serializing. Without this, BQSKit writes custom gate definitions into the
    # QASM header; if that QASM is later read by Qiskit or BQSKit again, the
    # hash-based gate name is already registered in the global gate registry and
    # raises "circuitgate_XXXX is already defined".
    try:
        from bqskit.passes import UnfoldPass
        from bqskit.compiler import Compiler, Workflow
        with Compiler(num_workers=1) as compiler:
            circ = compiler.compile(circ, Workflow([UnfoldPass()]))
    except Exception:
        pass  # if unfold fails for any reason, fall through and save as-is

    f = tempfile.NamedTemporaryFile("w+", suffix=".qasm", delete=False)
    try:
        f.close()
        circ.save(f.name)
        with open(f.name, "r") as g:
            return g.read()
    finally:
        try:
            os.remove(f.name)
        except OSError:
            pass


class BQSKITPass(QPass):
    name = "bqskit_pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, bqskit_passes):
        """
        bqskit_passes: iterable of BQSKit BasePass OR a BQSKit Workflow
        num_workers: forwarded to bqskit.compiler.Compiler
        request_data: if True, store BQSKit PassData mapping info into ctx.metadata
        """
        self.bqskit_passes = bqskit_passes
        self.num_workers = 1
        # self.pass_cfg = kwargs

    def get_compatible_backend(self, backend):
        from bqskit.compiler import MachineModel

        if isinstance(backend, MachineModel):
            return backend
        elif isinstance(backend, QBackend):
            # If it's already our BQSKITBackend subclass, it has to_bqskit_machine_model.
            return backend.to_bqskit_machine_model()
        elif isinstance(backend, str):
            backend = BQSKITBackend.from_json(backend)
            return backend.to_bqskit_machine_model()
        else:
            raise TypeError("Invalid type of backend given")

    def run(self, ctx: QPassContext) -> QPassContext:
        from bqskit.compiler import Compiler, Workflow
        from bqskit.passes import SetModelPass

        circ = _bqskit_circuit_from_qasm_str(ctx.qasm)

        # Build workflow
        # if hasattr(self.bqskit_passes, "run") and hasattr(self.bqskit_passes, "__iter__") is False:
        #     # very defensive: if someone passed a single pass object
        #     workflow = Workflow([self.bqskit_passes])
        # else:
        #     # WorkflowLike is a Workflow OR iterable of passes. :contentReference[oaicite:6]{index=6}
        workflow = Workflow(self.bqskit_passes)

        # If ctx.hardware exists, encode it into the workflow using SetModelPass.
        # (Compiler.compile itself does not take a model kwarg.) :contentReference[oaicite:7]{index=7} :contentReference[oaicite:8]{index=8}
        # Compaction logic: BQSKit often tries to build the unitary for the entire target machine.
        # If the machine has 127 qubits (FakeBrooklyn), it crashes if we pass the full model 
        # for a small circuit. We subset the model to only include active qubits.
        if getattr(ctx, "hardware", None) is not None:
            full_model = self.get_compatible_backend(ctx.hardware)
            
            # Find active physical qubits in the circuit
            import itertools
            active_qubits = sorted(list(set(itertools.chain.from_iterable(op.location for op in circ))))
            num_active = len(active_qubits)
            max_active = max(active_qubits) if active_qubits else 0
            
            # If the max qubit index is large (e.g., > 30), we must compact to avoid unitary dimension errors
            if max_active >= 30:
                from bqskit import Circuit
                from bqskit.compiler import MachineModel
                
                # Map physical -> logical (compact) indices
                phy_to_log = {phy: log for log, phy in enumerate(active_qubits)}
                log_to_phy = {log: phy for phy, log in phy_to_log.items()}
                
                # Build a new COMPACT circuit
                compact_circ = Circuit(num_active)
                for op in circ:
                    compact_circ.append_gate(op.gate, [phy_to_log[q] for q in op.location])
                
                # Create a subsetted MachineModel that only covers the active qubits
                new_edges = []
                if full_model.coupling_graph:
                    for u, v in full_model.coupling_graph:
                        if u in phy_to_log and v in phy_to_log:
                            new_edges.append((phy_to_log[u], phy_to_log[v]))
                
                sub_model = MachineModel(
                    num_active,
                    coupling_graph=new_edges if new_edges else None,
                    gate_set=full_model.gate_set
                )
                
                # Update workflow with the sub-model
                workflow = Workflow([SetModelPass(sub_model)]) + workflow
                
                # Run compilation on the compacted circuit
                with Compiler(num_workers=self.num_workers) as compiler:
                    compiled = compiler.compile(compact_circ, workflow)
                
                # Remap back to a circuit on the full hardware range
                final_circ = Circuit(full_model.num_qudits)
                for op in compiled:
                    final_circ.append_gate(op.gate, [log_to_phy[q] for q in op.location])
                
                ctx.qasm = _bqskit_circuit_to_qasm_str(final_circ)
                return ctx
            else:
                # Normal path for smaller circuits
                workflow = Workflow([SetModelPass(full_model)]) + workflow

        # Run compilation (Normal Path or Fallback)
        with Compiler(num_workers=self.num_workers) as compiler:
            compiled = compiler.compile(circ, workflow)

        ctx.qasm = _bqskit_circuit_to_qasm_str(compiled)
        return ctx




from qlego.registry import register_pass



@register_pass("Initialization")
class BqskitInit(BQSKITPass):
    def __init__(self):
        pass

    def run(self, ctx):
        from bqskit.passes import UnfoldPass, CompressPass, GroupSingleQuditGatePass

        # “init / normalize” stage: unfold higher-level gates and tidy.
        super().__init__([UnfoldPass(), GroupSingleQuditGatePass(), CompressPass()])
        return super().run(ctx)


class BaseBqskitLayoutPass(BQSKITPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_layout_algo(self, **kwargs):
        pass

    def run(self, ctx):
        from bqskit.passes import ApplyPlacement
        
        layout_algo = self.get_layout_algo(**self.pass_cfg)
        
        # BQSKit layout passes assign logical to physical mappings.
        # ApplyPlacement commits this mapping directly to the circuit operations.
        super().__init__([layout_algo, ApplyPlacement()])
        return super().run(ctx)

@register_pass("Layout")
class GeneralizedSabrePass(BaseBqskitLayoutPass):
    name = "Generalized Sabre"
    def get_layout_algo(self, **kwargs):
        from bqskit.passes import GeneralizedSabreLayoutPass
        return GeneralizedSabreLayoutPass(**kwargs)

@register_pass("Layout")
class TrivialPlacementPass(BaseBqskitLayoutPass):
    name = "Trivial Placement"
    def get_layout_algo(self, **kwargs):
        from bqskit.passes import TrivialPlacementPass
        return TrivialPlacementPass(**kwargs)

@register_pass("Layout")
class GreedyPlacementPass(BaseBqskitLayoutPass):
    name = "Greedy Placement"
    def get_layout_algo(self, **kwargs):
        from bqskit.passes import GreedyPlacementPass
        return GreedyPlacementPass(**kwargs)

@register_pass("Layout")
class PAMLayoutPass(BaseBqskitLayoutPass):
    name = "PAM Layout"
    def get_layout_algo(self, **kwargs):
        from bqskit.passes import PAMLayoutPass
        return PAMLayoutPass(**kwargs)

@register_pass("Layout")
class SubtopologySelectionPass(BaseBqskitLayoutPass):
    name = "Subtopology Selection"
    def get_layout_algo(self, **kwargs):
        try:
            from bqskit.passes.mapping.subtopology import SubtopologySelectionPass
            return SubtopologySelectionPass(**kwargs)
        except ImportError:
            # Fallback if specific version doesn't export this top-level
            from bqskit.passes import TrivialPlacementPass
            return TrivialPlacementPass(**kwargs)


class BaseBqskitRoutingPass(BQSKITPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_routing_algo(self, **kwargs):
        pass

    def run(self, ctx):
        routing_algo = self.get_routing_algo(**self.pass_cfg)
        super().__init__([routing_algo])
        return super().run(ctx)

@register_pass("Routing")
class GeneralizedSabreRoutingPass(BaseBqskitRoutingPass):
    name = "Generalized Sabre Routing"
    def get_routing_algo(self, **kwargs):
        from bqskit.passes import GeneralizedSabreRoutingPass
        return GeneralizedSabreRoutingPass(**kwargs)

@register_pass("Routing")
class PAMRoutingPass(BaseBqskitRoutingPass):
    name = "PAM Routing"
    def get_routing_algo(self, **kwargs):
        from bqskit.passes import PAMRoutingPass
        return PAMRoutingPass(**kwargs)


@register_pass("Translation")
class BqskitTranslation(BQSKITPass):
    def __init__(self):
        pass

    def run(self, ctx):
        from bqskit.passes import GeneralSQDecomposition, AutoRebase2QuditGatePass, UnfoldPass

        # Translate/rebase into the model's gate set:
        # - ensure single-qudit gates are expressed in the model's SQ family when possible
        # - automatically rebase 2-qudit gates to match the model’s 2Q gate(s)
        super().__init__([
            # GeneralSQDecomposition(), 
            UnfoldPass(),
            ])
        return super().run(ctx)


class BaseBqskitOptimizationPass(BQSKITPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_optimization_algo(self, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        opt_algo = self.get_optimization_algo(**self.pass_cfg)
        super().__init__([opt_algo])
        return super().run(ctx)

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class GroupSingleQuditGatePassPass(BaseBqskitOptimizationPass):
    name = "Group Single Qudit Gate Pass"
    def get_optimization_algo(self, **kwargs):
        from bqskit.passes import GroupSingleQuditGatePass as BqskitPass
        return BqskitPass(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class ScanningGateRemovalPassPass(BaseBqskitOptimizationPass):
    name = "Scanning Gate Removal Pass"
    def get_optimization_algo(self, **kwargs):
        from bqskit.passes import ScanningGateRemovalPass as BqskitPass
        return BqskitPass(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class IterativeScanningGateRemovalPassPass(BaseBqskitOptimizationPass):
    name = "Iterative Scanning Gate Removal Pass"
    def get_optimization_algo(self, **kwargs):
        from bqskit.passes import IterativeScanningGateRemovalPass as BqskitPass
        return BqskitPass(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class TreeScanningGateRemovalPassPass(BaseBqskitOptimizationPass):
    name = "Tree Scanning Gate Removal Pass"
    def get_optimization_algo(self, **kwargs):
        try:
            from bqskit.passes import TreeScanningGateRemovalPass as BqskitPass
            return BqskitPass(**kwargs)
        except ImportError:
            from bqskit.passes import ScanningGateRemovalPass as BqskitPass
            return BqskitPass(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class QuickPartitionerPass(BaseBqskitOptimizationPass):
    name = "Quick Partitioner"
    def get_optimization_algo(self, **kwargs):
        from bqskit.passes import QuickPartitioner
        block_size = kwargs.pop("block_size", 3)
        return QuickPartitioner(block_size, **kwargs)

# @register_pass("Optimization")
# class LEAPSynthesisPassPass(BaseBqskitOptimizationPass):
#     name = "LEAP Synthesis Pass"
#     def get_optimization_algo(self, **kwargs):
#         from bqskit.passes import LEAPSynthesisPass, QuickPartitioner
#         from bqskit.compiler import Workflow
#         # Synthesis is O(4^n). Using block_size=4 and loose threshold for speed.
#         block_size = kwargs.pop("block_size", 4)
#         kwargs.setdefault("success_threshold", 1e-3)
#         return Workflow([QuickPartitioner(block_size), LEAPSynthesisPass(**kwargs)])

# @register_pass("Optimization")
# class QSearchSynthesisPassPass(BaseBqskitOptimizationPass):
#     name = "QSearch Synthesis Pass"
#     def get_optimization_algo(self, **kwargs):
#         from bqskit.passes import QSearchSynthesisPass, QuickPartitioner
#         from bqskit.compiler import Workflow
#         # QSearch is very slow for > 2 qubits. Using block_size=2 for near-instant results.
#         block_size = kwargs.pop("block_size", 2)
#         kwargs.setdefault("success_threshold", 1e-3)
#         return Workflow([QuickPartitioner(block_size), QSearchSynthesisPass(**kwargs)])
