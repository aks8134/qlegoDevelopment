# qlego_qiskit/adapter/passes.py
from __future__ import annotations
from typing import Any, Dict, Optional
from qlego.qpass import QPass, QPassContext
from qlego_qiskit.adapter.passes import QiskitPass, QiskitRoutingPass


JSON = Dict[str, Any]

class LayoutPass(QiskitPass):
    name = "layout"

    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.transpiler.passes import (
            TrivialLayout,
            DenseLayout,
            ApplyLayout,
        )
        from qiskit.transpiler import CouplingMap
        self.coupling_map = CouplingMap([[0, 1], [1, 2]])
        if self.optimization_level <= 0:
            passes = [
                TrivialLayout(self.coupling_map),
                ApplyLayout(),
            ]
        else:
            passes = [
                DenseLayout(self.coupling_map),
                ApplyLayout(),
            ]

        super().__init__(passes)
        ctx = super().run(ctx)
        return ctx
    

class TranspileStage(QiskitPass):
    name = "Transpile Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = 3,#self.optimization_level,
            backend = backend
        )
    
        super().__init__([spm])
        ctx = super().run(ctx)
        return ctx
    

class DefaultLayoutPass(QiskitPass):
    name = "Qiskit Layout Pass"

    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx: QPassContext) -> QPassContext:
        from qiskit.transpiler import generate_preset_pass_manager, CouplingMap
        # self.coupling_map = CouplingMap([[0, 1], [1, 2]])
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        layout_pm = spm.layout
        super().__init__([spm.layout])
        ctx = super().run(ctx)
        return ctx
    
class InitStage(QiskitPass):
    name = "Init Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        init_pm = spm.init
        super().__init__([init_pm])
        ctx = super().run(ctx)
        return ctx
    
class RoutingStage(QiskitRoutingPass):
    name = "Routing Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        pm = spm.routing
        super().__init__([pm])
        ctx = super().run(ctx)
        return ctx
    
class TranslationStage(QiskitPass):
    name = "Translation Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        pm = spm.translation
        super().__init__([pm])
        ctx = super().run(ctx)
        return ctx
    
class OptimizationStage(QiskitPass):
    name = "Optimization Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        pm = spm.optimization
        super().__init__([pm])
        ctx = super().run(ctx)
        return ctx
    
class SchedulingStage(QiskitPass):
    name = "Scheduling Pass"
    def __init__(self, optimization_level: int = 2):
        # print(f"{self.__class__.__module__}:{self.__class__.__name__}")
        self.optimization_level = optimization_level
        

    @classmethod
    def from_config(cls, cfg: JSON) -> "LayoutPass":
        return cls(optimization_level=int(cfg.get("optimization_level", 2)))

    def to_config( self ):
        return {"optimization_level": self.optimization_level}
    
    def run(self, ctx):
        from qiskit.transpiler import generate_preset_pass_manager
        backend = self.get_compatible_backend(ctx.hardware)
        spm = generate_preset_pass_manager(
            optimization_level = self.optimization_level,
            backend = backend
        )
        pm = spm.scheduling
        super().__init__([pm])
        ctx = super().run(ctx)
        return ctx



# class InitStage(QiskitPass):
#     name = "init"

#     def __init__(self):
#         from qiskit.transpiler.passes import RemoveResetInZeroState, Unroll3qOrMore
#         from qiskit.transpiler.passes.synthesis.high_level_synthesis import HighLevelSynthesis
#         from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary

#         super().__init__([
#             RemoveResetInZeroState(),
#             Unroll3qOrMore(),
#             HighLevelSynthesis(equivalence_library=SessionEquivalenceLibrary),  # ✅ fixed
#         ])



# class LayoutStage(QiskitPass):
#     name = "layout"

#     def __init__(self, coupling_map, optimization_level: int):
        # from qiskit.transpiler.passes import (
        #     TrivialLayout,
        #     DenseLayout,
        #     ApplyLayout,
        # )

        # if optimization_level <= 0:
        #     passes = [
        #         TrivialLayout(coupling_map),
        #         ApplyLayout(),
        #     ]
        # else:
        #     passes = [
        #         DenseLayout(coupling_map),
        #         ApplyLayout(),
        #     ]

        # super().__init__(passes)

# class RoutingStage(QiskitPass):
#     name = "routing"

#     def __init__(self, coupling_map, seed: int | None):
#         from qiskit.transpiler.passes import SabreSwap

#         super().__init__([
#             SabreSwap(coupling_map, seed=seed)
#         ])


# class TranslationStage(QiskitPass):
#     name = "translation"

#     def __init__(self, basis_gates):
#         from qiskit.transpiler.passes import (
#             UnrollCustomDefinitions,
#             BasisTranslator,
#         )
#         from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary

#         super().__init__([
#             UnrollCustomDefinitions(SessionEquivalenceLibrary, basis_gates),
#             BasisTranslator(SessionEquivalenceLibrary, basis_gates),
#         ])


# def _import_cx_cancellation():
#     # Try common locations across Qiskit versions
#     try:
#         from qiskit.transpiler.passes.optimization import CXCancellation
#         return CXCancellation
#     except Exception:
#         pass

#     try:
#         from qiskit.transpiler.passes import CXCancellation
#         return CXCancellation
#     except Exception:
#         pass

#     # Fallback: older/newer versions may use a different name
#     # or not expose a dedicated CX cancellation pass publicly.
#     return None

# class OptimizationStage(QiskitPass):
#     name = "optimization"

#     def __init__(self, basis_gates, optimization_level: int):
#         from qiskit.transpiler.passes import (
#             Optimize1qGatesDecomposition,
#             CommutativeCancellation,
#         )

#         CXCancellation = _import_cx_cancellation()

#         passes = []
#         if optimization_level >= 1:
#             passes.append(Optimize1qGatesDecomposition(basis=basis_gates))
#             if CXCancellation is not None:
#                 passes.append(CXCancellation())
#         if optimization_level >= 2:
#             passes.append(CommutativeCancellation())

#         super().__init__(passes)


# class SchedulingStage(QiskitPass):
#     name = "scheduling"

#     def __init__(self, instruction_durations):
#         if instruction_durations is None:
#             super().__init__([])
#         else:
#             from qiskit.transpiler.passes import ALAPSchedule
#             super().__init__([
#                 ALAPSchedule(instruction_durations)
#             ])
