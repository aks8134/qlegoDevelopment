from __future__ import annotations
import os
# core/tket_remote_pass.py

import json
import os
import subprocess
from typing import Any, Dict, Optional

from qlego.qpass import QPass, QPassContext
from qlego_tket.adapter.backend import QBackend, TketBackend
JSON = Dict[str, Any]


class TKetPass(QPass):
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.venv/bin/python"))
    def __init__(self, tket_passes):
        self.tket_passes = tket_passes

    def get_compatible_backend(self, backend):
        from pytket.backends.backendinfo import BackendInfo

        if(isinstance(backend, BackendInfo)):
            return backend
        elif(isinstance(backend, QBackend)):
            return backend.to_tket_backend_info()
        elif(isinstance(backend, str)):
            backend = TketBackend.from_json(backend)
            return backend.to_tket_backend_info()
        else:
            raise TypeError("Invalid type of backend given")

    def run( self, ctx: QPassContext ):
        from pytket.qasm import circuit_from_qasm_str, circuit_to_qasm_str
        from pytket.passes import BasePass, SequencePass, AutoRebase
        from pytket.circuit import OpType

        circ = circuit_from_qasm_str(ctx.qasm)

        # Make implicit wire swaps explicit so optimization passes see a standard graph
        # This prevents "Vertex has multiple inputs on the same port" errors in passes like DelayMeasures
        circ.replace_implicit_wire_swaps()

        # Apply passes in-place
        for p in self.tket_passes:
            if isinstance(p, BasePass):
                p.apply(circ)
            elif isinstance(p, (list, tuple)):
                SequencePass(list(p)).apply(circ)
            else:
                raise TypeError(f"Incompatible tket pass type: {type(p)}")

        # Rebase to QASM-compatible gates if necessary
        # pytket's qasm export is sensitive to non-standard gates like PhasedX
        # We rebase to {CX, TK1} which covers all state-space while remaining QASM-friendly (TK1 -> u3)
        from pytket.passes import DecomposeBoxes
        try:
            # First try decomposing any defined boxes (like Qiskit custom gates)
            DecomposeBoxes().apply(circ)
            AutoRebase({OpType.CX, OpType.TK1}).apply(circ)
        except RuntimeError as e:
            if "basic gates: CustomGate" in str(e):
                # An opaque custom block (e.g., from BQSKit QuickPartitioner) is present.
                # AutoRebase cannot process opaque blocks, so we skip rebasing.
                pass
            else:
                raise e

        ctx.qasm = circuit_to_qasm_str(circ, header="qelib1")

        return ctx

    # def executor(self, ctx: QPassContext) -> QPassContext:
    #     payload = {
    #         "pass_cfg": self.to_config(),
    #         "ctx": {
    #             "qasm": ctx.qasm,
    #             "seed": ctx.seed,
    #             "hardware": ctx.hardware,
    #             "metadata": ctx.metadata,
    #         },
    #     }

    #     proc = subprocess.run(
    #         ["./tket_plugin/.venv/bin/python",
    #           "-u", 
    #           "-m",
    #           "core.worker",
    #           "--pass-class", 
    #           self.c_name()
    #         ],
    #         input=json.dumps(payload),
    #         text=True,
    #         capture_output=True,
    #         env=os.environ.copy(),
    #     )

    #     if proc.returncode != 0:
    #         raise RuntimeError(f"tket worker failed\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}")

    #     # Parse last JSON object in stdout (robust to stray prints)
    #     lines = proc.stdout.splitlines()
    #     json_line = next((ln for ln in reversed(lines) if ln.lstrip().startswith("{")), None)
    #     if json_line is None:
    #         raise RuntimeError(f"No JSON in tket worker stdout:\n{proc.stdout}")

    #     out = json.loads(json_line)["ctx"]
    #     ctx.qasm = out["qasm"]
    #     ctx.metadata = out.get("metadata", ctx.metadata)
    #     return ctx

from qlego.registry import register_pass

from qlego_tket.adapter.backend import QBackend, TketBackend


@register_pass("Initialization")
class TketInit(TKetPass):
    def __init__(self):
        pass
    def run(self, ctx):
        from pytket.passes import DecomposeBoxes, DecomposeMultiQubitsCX

        super().__init__([DecomposeBoxes(), DecomposeMultiQubitsCX()])
        ctx = super().run(ctx)
        return ctx


class BaseTketLayoutPass(TKetPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg
        
    def get_placement_algo(self, arch, backend_info=None, **kwargs):
        pass
        
    def run(self, ctx):
        from pytket.qasm import circuit_from_qasm_str, circuit_to_qasm_str
        
        backend_info = self.get_compatible_backend(ctx.hardware)
        arch = backend_info.architecture
        placement_algo = self.get_placement_algo(arch, backend_info=backend_info, **self.pass_cfg)
        
        circ = circuit_from_qasm_str(ctx.qasm)
        try:
            placement_map = placement_algo.get_placement_map(circ)
        except Exception as e:
            raise RuntimeError(f"TKET placement algorithm failed: {e}")
            
        if not placement_map:
            raise RuntimeError("TKET placement failed to generate a valid map")
            
        # TKET placement algorithms lazily assign 'unplaced' Nodes if the subgraph isomorphism fails
        # (e.g. strict line placement over a highly rigid star-graph DJ Circuit). We must cleanly 
        # intercept and raise so the logger can mark this algorithm as Failed.
        for node in placement_map.values():
            if getattr(node, "reg_name", "") == "unplaced" or "unplaced" in str(node):
                raise RuntimeError("Layout algorithm failed to find a valid mapping.")
                
        # Physically apply the layout to the circuit replacing logical qubits with physical Hardware Nodes
        circ.rename_units(placement_map)
        
        # QLego inter-SDK handoffs: to allow Qiskit routers (like SabreSwap) to handle this QASM downstream,
        # we must artificially pad the circuit to the full architecture size (similar to FullAncillaAllocation)
        for node in arch.nodes:
            if node not in circ.qubits:
                circ.add_qubit(node)
                
        # Make implicit wire swaps explicit so the QASM reflects routing changes
        circ.replace_implicit_wire_swaps()
        
        ctx.qasm = circuit_to_qasm_str(circ, header="qelib1")
        return ctx

@register_pass("Layout")
class LinePlacementPass(BaseTketLayoutPass):
    name = "Line Placement"
    def get_placement_algo(self, arch, backend_info=None, **kwargs):
        from pytket.placement import LinePlacement
        return LinePlacement(arch, **kwargs)

@register_pass("Layout")
class GraphPlacementPass(BaseTketLayoutPass):
    name = "Graph Placement"
    def get_placement_algo(self, arch, backend_info=None, **kwargs):
        from pytket.placement import GraphPlacement
        return GraphPlacement(arch, **kwargs)

@register_pass("Layout")
class NoiseAwarePlacementPass(BaseTketLayoutPass):
    name = "Noise Aware Placement"
    def get_placement_algo(self, arch, backend_info=None, **kwargs):
        from pytket.placement import NoiseAwarePlacement
        
        valid_kwargs = kwargs.copy()
        
        if backend_info:
            node_errors = getattr(backend_info, "averaged_node_gate_errors", None)
            if node_errors is not None:
                valid_kwargs["node_errors"] = node_errors
                
            link_errors = getattr(backend_info, "averaged_edge_gate_errors", None)
            if link_errors is not None:
                valid_kwargs["link_errors"] = link_errors
                
            readout_errors = getattr(backend_info, "averaged_readout_errors", None)
            if readout_errors is not None:
                valid_kwargs["readout_errors"] = readout_errors
                
        return NoiseAwarePlacement(arch, **valid_kwargs)
    
class BaseTketRoutingPass(TKetPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg
        
    def get_routing_algo(self, arch, **kwargs):
        pass
        
    def run(self, ctx):
        from pytket.passes import RemoveBarriers
        from pytket.qasm import circuit_from_qasm_str, circuit_to_qasm_str
        from pytket import Circuit, OpType
        
        backend_info = self.get_compatible_backend(ctx.hardware)
        arch = backend_info.architecture
        routing_algo = self.get_routing_algo(arch, **self.pass_cfg)
        
        circ = circuit_from_qasm_str(ctx.qasm)
        
        # Strip external classical dependencies and barriers from the TKET Circuit that TKET's graph 
        # syntheis routing (AASRoute) chokes on or loses references to.
        clean_circ = Circuit(circ.name) if circ.name else Circuit()
        for q in circ.qubits:
            clean_circ.add_qubit(q)
        # AASRoute crashes if it encounters classical bits or Measure operations, so we drop them
        for cmd in circ.get_commands():
            if cmd.op.type not in [OpType.Measure, OpType.Barrier]:
                clean_circ.add_gate(cmd.op, cmd.args)
                
        # TKet routers (like AASRoute) might additionally benefit from native RemoveBarriers()
        RemoveBarriers().apply(clean_circ)
        
        # TKet imports QASM `gate custom` definitions as opaque CustomGate boxes,
        # which routing synthesis cannot natively process. Decompose them into primitive Operations.
        from pytket.passes import DecomposeBoxes
        DecomposeBoxes().apply(clean_circ)

        routing_algo.apply(clean_circ)
        
        ctx.qasm = circuit_to_qasm_str(clean_circ, header="qelib1")
        return ctx
        
@register_pass("Routing")
class TketDefaultRoutingPass(BaseTketRoutingPass):
    name = "Tket Default Routing"
    def get_routing_algo(self, arch, **kwargs):
        from pytket.passes import RoutingPass
        return RoutingPass(arch)

@register_pass("Routing")
class AASRoutePass(BaseTketRoutingPass):
    name = "AAS Route"
    def get_routing_algo(self, arch, **kwargs):
        from pytket.passes import AASRouting
        return AASRouting(arch, tobject=kwargs.get("lookahead", 1))

@register_pass("Routing")
class LexiRoutePass(BaseTketRoutingPass):
    name = "Lexi Route"
    def get_routing_algo(self, arch, **kwargs):
        from pytket.passes import LexiRouteRoutingPass
        return LexiRouteRoutingPass(arch)

@register_pass("Routing")
class BoxDecomposeRoutePass(BaseTketRoutingPass):
    name = "Box Decompose Route"
    def get_routing_algo(self, arch, **kwargs):
        try:
            from pytket.passes import Box2QRoutePass
            return Box2QRoutePass(arch)
        except ImportError:
            # Fallback for routing pass typically used if box decompose router is unavailable in specific pytket version
            from pytket.passes import DefaultMappingPass
            return DefaultMappingPass(arch)
    
@register_pass("Translation")
class TketTranslation(TKetPass):
    def __init__(self):
        pass
    def run(self, ctx):
        from pytket.passes import AutoRebase
        backend_info = self.get_compatible_backend(ctx.hardware)
        translation = AutoRebase(backend_info.gate_set)
        super().__init__([translation])
        ctx = super().run(ctx)
        return ctx





class BaseTketOptimizationPass(TKetPass):
    def __init__(self, **kwargs):
        self.pass_cfg = kwargs

    def to_config(self):
        return self.pass_cfg

    def get_optimization_algo(self, **kwargs):
        pass

    def run(self, ctx: QPassContext) -> QPassContext:
        from pytket.passes import DecomposeBoxes
        opt_algo = self.get_optimization_algo(**self.pass_cfg)
        super().__init__([DecomposeBoxes(), opt_algo])
        ctx = super().run(ctx)
        return ctx

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class SquashTK1Pass(BaseTketOptimizationPass):
    name = "Squash TK1"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import SquashTK1
        return SquashTK1(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class SquashRzPhasedXPass(BaseTketOptimizationPass):
    name = "Squash Rz Phased X"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import SquashRzPhasedX
        return SquashRzPhasedX(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: 1q Simplification")
class DecomposeSingleQubitsTK1Pass(BaseTketOptimizationPass):
    name = "Decompose Single Qubits TK1"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import DecomposeSingleQubitsTK1
        return DecomposeSingleQubitsTK1(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class FullPeepholeOptimizePass(BaseTketOptimizationPass):
    name = "Full Peephole Optimize"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import FullPeepholeOptimise
        return FullPeepholeOptimise(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Clifford-Aware")
class CliffordSimpPass(BaseTketOptimizationPass):
    name = "Clifford Simp"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import CliffordSimp
        return CliffordSimp(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class PeepholeOptimize2QPass(BaseTketOptimizationPass):
    name = "Peephole Optimize 2Q"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import PeepholeOptimise2Q
        return PeepholeOptimise2Q(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class KAKDecompositionPass(BaseTketOptimizationPass):
    name = "KAK Decomposition"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import KAKDecomposition
        return KAKDecomposition(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class RemoveRedundanciesPass(BaseTketOptimizationPass):
    name = "Remove Redundancies"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import RemoveRedundancies
        return RemoveRedundancies(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Commutation & Algebraic")
class RemovePhaseOpsPass(BaseTketOptimizationPass):
    name = "Remove Phase Ops"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import RemovePhaseOps
        return RemovePhaseOps(**kwargs)
@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class DelayMeasuresPass(BaseTketOptimizationPass):
    name = "Delay Measures"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import DelayMeasures
        return DelayMeasures(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class SimplifyMeasuresPass(BaseTketOptimizationPass):
    name = "Simplify Measures"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import SimplifyMeasured
        return SimplifyMeasured(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Measurement & Terminal Cleanup")
class RemoveDiscardedPass(BaseTketOptimizationPass):
    name = "Remove Discarded"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import RemoveDiscarded
        return RemoveDiscarded(**kwargs)

@register_pass("Optimization")
@register_pass("Bundle: Block Collection + Synthesis")
class SynthesiseTketPass(BaseTketOptimizationPass):
    name = "Synthesise Tket"
    def get_optimization_algo(self, **kwargs):
        from pytket.passes import SynthesiseTket
        return SynthesiseTket(**kwargs)
