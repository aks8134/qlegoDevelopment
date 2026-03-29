import os
from qlego.qpass import QPass, QPassContext 
import subprocess
import json
from .backend import QiskitBackend, QBackend
from typing import Any, Dict, Optional
JSON = Dict[str, Any]
from qlego.registry import register_pass
#TODO : Think about need for getting layout information
def _extract_layouts_from_property_set(ps, qc, final_circ=None):
    """
    Return (current_layout, final_layout) as lists where:
      layout[i] = physical_qubit_index assigned to logical qubit i
    """
    # Most reliable: use the compiled circuit's own TranspileLayout when available.
    # generate_preset_pass_manager does NOT always populate property_set["transpile_layout"],
    # but always sets final_circ._layout after a full run.
    # Only trust it if _input_qubit_count < total qubits (i.e., it has real ancilla tracking
    # from a full compilation, not a sub-stage identity layout).
    if final_circ is not None and final_circ.layout is not None:
        tl = final_circ.layout
        if tl._input_qubit_count is not None and tl._input_qubit_count < len(final_circ.qubits):
            current = tl.initial_index_layout(filter_ancillas=True)
            final = tl.final_index_layout(filter_ancillas=True)
            return list(current), list(final)

    # Preferred: TranspileLayout has both initial and final permutations
    tl = ps.get("transpile_layout", None)
    if tl is not None:
        # In Qiskit, these are index-based layouts (good for serialization)
        current = tl.initial_index_layout(filter_ancillas=True)
        final = tl.final_index_layout(filter_ancillas=True)
        return list(current), list(final)

    # Fallback: sometimes only 'layout' is present (pre-routing)
    layout = ps.get("layout", None)
    final_layout_obj = ps.get("final_layout", None)

    if layout is not None:
        # layout maps Qubit objects -> physical indices
        current = []
        for i, q in enumerate(qc.qubits):
            if q in layout:
                current.append(layout[q])
            else:
                current.append(i)

        if final_layout_obj is not None:
            # final_layout_obj maps final_circ.qubits -> physical indices.
            # Build from final_circ.qubits directly (not qc.qubits which may differ).
            final = []
            if final_circ is not None:
                for i in range(len(final_circ.qubits)):
                    fq = final_circ.qubits[i]
                    if fq in final_layout_obj:
                        final.append(final_layout_obj[fq])
                    else:
                        final.append(i)
            else:
                for i, q in enumerate(qc.qubits):
                    if q in final_layout_obj:
                        final.append(final_layout_obj[q])
                    else:
                        final.append(current[i] if i < len(current) else i)
        else:
            final = list(current)

        return list(current), final
        
    return None, None

class QiskitPass(QPass):
    name = "qiskit_pass"
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, qiskit_passes):
        self.qiskit_passes = qiskit_passes

    def get_compatible_backend(self, backend):
        from qiskit.providers import Backend
        if( isinstance(backend, Backend)):
            return backend
        elif(isinstance(backend, QBackend)):
            return backend.to_qiskit_backend()
        elif(isinstance(backend, str)):
            backend = QiskitBackend.from_json(backend)
            return backend.to_qiskit_backend()
        else:
            raise TypeError("Invalid type of backend given")

    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.qasm2 import loads, dumps, LEGACY_CUSTOM_INSTRUCTIONS # qasm2/qasm3 here
        from qiskit.transpiler import PassManager, PropertySet, Layout
        from qiskit.transpiler.basepasses import BasePass
        from qiskit.passmanager import BasePassManager
        from qiskit.transpiler.passes import SetLayout
        import pickle
        qc = loads(ctx.qasm, custom_instructions=LEGACY_CUSTOM_INSTRUCTIONS)
        pm = PassManager()
        if(ctx.metadata.get("layout_needed", False)):
            current_layout = Layout({qb: i for i, qb in enumerate(qc.qubits)})
            pm.append(SetLayout(current_layout))
            
        if(ctx.metadata.get("mock_transpile_layout", False)):
            from qiskit.transpiler import AnalysisPass
            class InitTranspileLayout(AnalysisPass):
                def run(self, dag):
                    from qiskit.transpiler import TranspileLayout, Layout
                    if "layout" not in self.property_set:
                        layout = Layout({qb: i for i, qb in enumerate(dag.qubits)})
                        self.property_set["layout"] = layout
                    else:
                        layout = self.property_set["layout"]
                    
                    if "transpile_layout" not in self.property_set:
                        mapping = {qb: i for i, qb in enumerate(dag.qubits)}
                        final_layout_obj = self.property_set.get("final_layout", layout)
                        tl = TranspileLayout(
                            initial_layout=layout,
                            input_qubit_mapping=mapping,
                            final_layout=final_layout_obj,
                            _input_qubit_count=len(dag.qubits),
                            _output_qubit_list=dag.qubits
                        )
                        self.property_set["transpile_layout"] = tl
            pm.append(InitTranspileLayout())
        for pass_i in self.qiskit_passes:
            if pass_i is None:
                continue
            elif( isinstance(pass_i, BasePass) ):
                pm.append(pass_i)
            elif( isinstance(pass_i, BasePassManager)):
                pm.append(pass_i.to_flow_controller())
            else:
                raise TypeError(f"Incompatible QiskitPass Encountered: {type(pass_i)}; use PassManager or Pass")
            

        final_circ = pm.run(qc)
        
        # Decompose any high-level objects like Clifford or UnitaryGate 
        # that standard QASM export doesn't handle natively
        from qiskit.circuit import Instruction
        from qiskit.quantum_info import Clifford
        
        # Identify non-instruction operations (like Clifford) that cause QASM export errors
        if any(not isinstance(inst.operation, Instruction) for inst in final_circ.data):
            final_circ = final_circ.decompose()
            
        ctx.qasm = dumps(final_circ)
        
        # Serialize layout data across the qlego execution pipeline
        init_layout, final_layout = _extract_layouts_from_property_set(pm.property_set, qc, final_circ)
        if init_layout is not None:
            ctx.metadata["layout"] = {"initial": init_layout, "final": final_layout}
            
        return ctx

    


####################Preset Passes###########################
class BasePresetPass(QiskitPass):
    def __init__(self, **kwargs ):
        self.pass_config = kwargs
    
    def to_config(self):
        return self.pass_config
    
    def get_processed_pass(self, **kwargs):
        raise NotImplementedError
    
    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.pass_config.get("optimization_level", 2),
            backend = backend,
            seed_transpiler = self.pass_config.get("seed_transpiler", 0)
        )
        pm = self.get_processed_pass(spm)
        super().__init__([pm])
        ctx = super().run(ctx)
        return ctx

@register_pass("EndToEnd")
class PresetPasses(BasePresetPass):
    name = "Preset Pass Manager"
    def get_processed_pass(self, spm):
        return spm

@register_pass("Initialization")
class PresetInitPass(BasePresetPass):
    name = "Preset Init Pass"
    def get_processed_pass(self, spm):
        return spm.init

@register_pass("Scheduling")
class PresetSchedulingPass(BasePresetPass):
    name = "Preset Scheduling Pass"
    def get_processed_pass(self, spm):
        return spm.scheduling

@register_pass("Translation")
class PresetTranslationPass(BasePresetPass):
    name = "Preset Translation Pass"
    def get_processed_pass(self, spm):
        return spm.translation

###################Layout Pass###########################
class BaseLayoutPass(QiskitPass):
    def __init__(self, **kwargs):
        self.pass_config = kwargs
    
    def to_config(self):
        return self.pass_config

    def get_layout_algo( self, backend, **kwargs ):
        pass
    
    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.transpiler.passes import ApplyLayout, FullAncillaAllocation, EnlargeWithAncilla
        from qiskit.transpiler.basepasses import AnalysisPass
        from qiskit.transpiler.exceptions import TranspilerError
        
        backend = self.get_compatible_backend(ctx.hardware)
        layout_pass = self.get_layout_algo(backend)
        
        class CheckLayoutPass(AnalysisPass):
            def run(self, dag):
                if self.property_set.get('layout') is None:
                    raise TranspilerError('Layout algorithm failed to find a valid mapping.')
                    
        passes = [
            layout_pass, 
            CheckLayoutPass(),
            FullAncillaAllocation(backend.target),
            EnlargeWithAncilla(),
            ApplyLayout()
        ]
        super().__init__(passes)
        ctx = super().run(ctx)
        return ctx

@register_pass("Layout")
class TrivialLayoutPass(BaseLayoutPass):
    name = "Trivial Layout"
    def get_layout_algo( self, backend ):
        from qiskit.transpiler.passes import TrivialLayout
        return TrivialLayout(backend.target)

@register_pass("Layout")
class DenseLayoutPass(BaseLayoutPass):
    name = "Dense Layout"
    def get_layout_algo( self, backend ):
        from qiskit.transpiler.passes import DenseLayout
        return DenseLayout(target=backend.target)

@register_pass("Layout")
class SabreLayoutPass(BaseLayoutPass):
    name = "Sabre Layout"
    def get_layout_algo( self, backend ):
        from qiskit.transpiler.passes import SabreLayout
        return SabreLayout(backend.target)

    def run(self, ctx: QPassContext) -> QPassContext:
        backend = self.get_compatible_backend(ctx.hardware)
        layout_pass = self.get_layout_algo(backend)
        
        # SabreLayout in Qiskit 1.0+ is a TransformationPass that internally 
        # mutates the DAG, applying layout, routing, and ancilla injection. 
        # Attempting to re-run FullAncillaAllocation or ApplyLayout triggers KeyError 
        # due to hashing mismatches and mutated states.
        passes = [
            layout_pass
        ]
        from qlego_qiskit.adapter.passes import QiskitPass
        QiskitPass.__init__(self, passes)
        ctx = QiskitPass.run(self, ctx)
        return ctx

@register_pass("Layout")
class VF2LayoutPass(BaseLayoutPass):
    name = "VF2 Layout"
    def get_layout_algo( self, backend ):
        from qiskit.transpiler.passes import VF2Layout
        return VF2Layout(target=backend.target)

@register_pass("Layout")
class CSPLayoutPass(BaseLayoutPass):
    name = "CSP Layout"
    def get_layout_algo( self, backend ):
        from qiskit.transpiler.passes import CSPLayout
        if hasattr(backend, 'coupling_map') and backend.coupling_map is not None:
            return CSPLayout(backend.coupling_map)
        return CSPLayout(backend.target)

@register_pass("Layout")
class PresetLayoutPass(BasePresetPass):
    name = "Preset Layout Pass"
    def get_processed_pass(self, spm):
        return spm.layout
    
#########################Routing####################################
class BaseRoutingPass(QiskitPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_routing_algo(self, backend, **kwargs):
        pass
    def run(self, ctx: QPassContext) -> QPassContext:
        pre_routing_initial = ctx.metadata.get("layout", {}).get("initial", None)
        ctx.metadata["layout_needed"] = True
        backend = self.get_compatible_backend(ctx.hardware)
        super().__init__([self.get_routing_algo(backend)])
        ctx = super().run(ctx)
        ctx.metadata.pop("layout_needed", None)
        if pre_routing_initial is not None and "layout" in ctx.metadata:
            # routing_full_initial may differ from pre_routing_initial if VF2PostLayout
            # (included at optimization levels 2+) changed the initial placement.
            routing_full_initial = ctx.metadata["layout"]["initial"]
            routing_full_final = ctx.metadata["layout"]["final"]
            ctx.metadata["layout"]["initial"] = [routing_full_initial[p] for p in pre_routing_initial]
            ctx.metadata["layout"]["final"] = [routing_full_final[p] for p in pre_routing_initial]
        return ctx

@register_pass("Routing")
class PresetRoutingPass(BasePresetPass):
    name = "Preset Routing Pass"
    def get_processed_pass(self, spm):
        return spm.routing

    def run(self, ctx):
        pre_routing_initial = ctx.metadata.get("layout", {}).get("initial", None)
        ctx.metadata["layout_needed"] = True
        ctx = super().run(ctx)
        ctx.metadata.pop("layout_needed", None)
        if pre_routing_initial is not None and "layout" in ctx.metadata:
            routing_full_initial = ctx.metadata["layout"]["initial"]
            routing_full_final = ctx.metadata["layout"]["final"]
            ctx.metadata["layout"]["initial"] = [routing_full_initial[p] for p in pre_routing_initial]
            ctx.metadata["layout"]["final"] = [routing_full_final[p] for p in pre_routing_initial]
        return ctx
    

@register_pass("Routing")
class SabreSwapRoutingPass(BaseRoutingPass):
    name = "Sabre Swap Routing Pass"
    def get_routing_algo(self, backend):
        from qiskit.transpiler.passes import SabreSwap
        return SabreSwap(backend.target)

@register_pass("Routing")
class BasicSwapRoutingPass(BaseRoutingPass):
    name = "Basic Swap Routing Pass"
    def get_routing_algo(self, backend):
        from qiskit.transpiler.passes import BasicSwap
        return BasicSwap(backend.target)
    
@register_pass("Routing")
class LookaheadRoutingPass(BaseRoutingPass):
    name = "Lookahead Routing Pass"
    def get_routing_algo(self, backend):
        from qiskit.transpiler.passes import LookaheadSwap
        return LookaheadSwap(backend.target)

@register_pass("Routing")
class StochasticSwapRoutingPass(BaseRoutingPass):
    name = "Stochastic Swap Routing Pass"
    def get_routing_algo(self, backend):
        try:
            from qiskit.transpiler.passes import StochasticSwap
            return StochasticSwap(backend.target)
        except ImportError:
            from qiskit.transpiler.passes import SabreSwap
            # Dummy heuristic setup since SabreSwap requires more arguments natively in Qiskit 1.x!
            from qiskit.transpiler.passes.routing.sabre_swap import SabreSwap
            # Actually SabreSwap takes coupling_map instead of target natively, plus heuristic
            # It's better to just return SabreSwap with minimal necessary args based on Qiskit version
            from qiskit.transpiler.passes import BasicSwap
            # Fallback to BasicSwap since SabreSwap API changed drastically (requires layout explicitly)
            return BasicSwap(backend.target)

# @register_pass("Routing")
# class Commuting2qGateRouterPass(BaseRoutingPass):
#     name = "Commuting 2q Gate Router Pass"
#     def get_routing_algo(self, backend):
#         from qiskit.transpiler.passes import Commuting2qGateRouter
#         return Commuting2qGateRouter(backend.target)


###################Optimization####################################
@register_pass("Optimization")
class PresetOptimizationPass(BasePresetPass):
    name = "Preset Optimization Pass"
    def get_processed_pass(self, spm):
        return spm.optimization

    def run(self, ctx: QPassContext) -> QPassContext:
        # Save layout before running: the mock_transpile_layout mechanism injects
        # an identity TranspileLayout so optimization passes don't crash, but that
        # fake layout then gets extracted and overwrites the real placement/routing
        # layout.  Restore it afterwards since optimization never changes qubit mapping.
        saved_layout = ctx.metadata.get("layout", None)
        ctx.metadata["mock_transpile_layout"] = True
        ctx = super().run(ctx)
        ctx.metadata.pop("mock_transpile_layout", None)
        if saved_layout is not None:
            ctx.metadata["layout"] = saved_layout
        return ctx
    
class BaseOptimizationPass(QiskitPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_optimization_algo(self, backend, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        backend = self.get_compatible_backend(ctx.hardware)
        opt_algo = self.get_optimization_algo(backend, **self.pass_cfg)
        super().__init__([opt_algo])
        ctx = super().run(ctx)
        return ctx

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class Optimize1qGatesPass(BaseOptimizationPass):
    name = "Optimize 1q Gates"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import Optimize1qGates
        return Optimize1qGates(target=backend.target, **kwargs)

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class Optimize1qGateDecompositionPass(BaseOptimizationPass):
    name = "Optimize 1q Gate Decomposition"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import Optimize1qGatesDecomposition
        return Optimize1qGatesDecomposition(target=backend.target, **kwargs)

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class Optimize1qGateSimpleCommutationPass(BaseOptimizationPass):
    name = "Optimize 1q Gate Simple Commutation"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import Optimize1qGatesSimpleCommutation
        return Optimize1qGatesSimpleCommutation(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class CommutativeCancellationPass(BaseOptimizationPass):
    name = "Commutative Cancellation"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import CommutativeCancellation
        return CommutativeCancellation(target=backend.target, **kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class CommutationAnalysisPass(BaseOptimizationPass):
    name = "Commutation Analysis"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import CommutationAnalysis
        return CommutationAnalysis(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class CommutativeOptimizationPass(BaseOptimizationPass):
    name = "Commutative Optimization"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import CommutativeOptimization
        return CommutativeOptimization(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Clifford-Aware")
class OptimizeCliffordsPass(BaseOptimizationPass):
    name = "Optimize Cliffords"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import OptimizeCliffords
        return OptimizeCliffords(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Clifford-Aware")
class OptimizeCliffordTPass(BaseOptimizationPass):
    name = "Optimize Clifford T"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import OptimizeCliffordT
        return OptimizeCliffordT(**kwargs)
        
@register_pass("Optimization")
@register_pass("Bundle: Clifford-Aware")
class CollectCliffordsPass(BaseOptimizationPass):
    name = "Collect Cliffords"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import CollectCliffords
        return CollectCliffords(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class Collect2qBlocksPass(BaseOptimizationPass):
    name = "Collect 2q Blocks"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import Collect2qBlocks
        return Collect2qBlocks(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class CollectMultiQBlocksPass(BaseOptimizationPass):
    name = "Collect Multi Q Blocks"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import CollectMultiQBlocks
        return CollectMultiQBlocks(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Identity & Cleanup")
class RemoveIdentityEquivalentPass(BaseOptimizationPass):
    name = "Remove Identity Equivalent"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import RemoveIdentityEquivalent
        return RemoveIdentityEquivalent(target=backend.target, **kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class OptimizeSwapBeforeMeasurePass(BaseOptimizationPass):
    name = "Optimize Swap Before Measure"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import OptimizeSwapBeforeMeasure
        return OptimizeSwapBeforeMeasure(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class RemoveDiagonalGatesBeforeMeasurePass(BaseOptimizationPass):
    name = "Remove Diagonal Gates Before Measure"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import RemoveDiagonalGatesBeforeMeasure
        return RemoveDiagonalGatesBeforeMeasure(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class RemoveFinalResetPass(BaseOptimizationPass):
    name = "Remove Final Reset"
    def get_optimization_algo(self, backend, **kwargs):
        from qiskit.transpiler.passes import RemoveFinalReset
        return RemoveFinalReset(**kwargs)

# @register_pass("Optimization")
# class ResetAfterMeasureSimplificationPass(BaseOptimizationPass):
#     name = "Reset After Measure Simplification"
#     def get_optimization_algo(self, backend, **kwargs):
#         from qiskit.transpiler.passes import ResetAfterMeasureSimplification
#         return ResetAfterMeasureSimplification(**kwargs)

# @register_pass("Optimization")
# class TranslateParametrizedGatesPass(BaseOptimizationPass):
#     name = "Translate Parametrized Gates"
#     def get_optimization_algo(self, backend, **kwargs):
#         try:
#             from qiskit.transpiler.passes import TranslateParameterizedGates
#             from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary as sel
#             return TranslateParameterizedGates(sel, **kwargs)
#         except ImportError:
#             from qiskit.transpiler.passes import BasisTranslator
#             from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary as sel
#             target_basis = kwargs.get("target_basis", ["cx", "id", "rz", "sx", "x"])
#             return BasisTranslator(sel, target_basis=target_basis)
# #             ])
