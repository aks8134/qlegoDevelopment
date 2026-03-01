from qlego.qpass import QPass, QPassContext
from qlego_tket.adapter.passes import TKetPass
from qlego_tket.adapter.backend import QBackend, TketBackend


class TketInit(TKetPass):
    def __init__(self):
        pass
    def run(self, ctx):
        from pytket.passes import DecomposeBoxes, DecomposeMultiQubitsCX

        super().__init__([DecomposeBoxes(), DecomposeMultiQubitsCX()])
        ctx = super().run(ctx)
        return ctx


class TketPlacement(TKetPass):
    def __init__(self):
        pass
    def run( self, ctx ):
        from pytket.passes import PlacementPass
        from pytket.placement import GraphPlacement
        backend_info = self.get_compatible_backend(ctx.hardware)
        arch = backend_info.architecture
        placement = PlacementPass(GraphPlacement(arch))
        super().__init__([placement])
        ctx = super().run(ctx)
        return ctx
    
class TketRouting(TKetPass):
    def __init__(self):
        pass
    def run(self, ctx):
        from pytket.passes import RoutingPass
        backend_info = self.get_compatible_backend(ctx.hardware)
        arch = backend_info.architecture
        routing = RoutingPass(arch)
        super().__init__([routing])
        ctx = super().run(ctx)
        return ctx
    
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





class TkETOptimisePass(TKetPass):
    name = "Tket Optimise Pass"

    def __init__(self, level: int = 1):
        self.level = int(level)

    @classmethod
    def from_config(cls, cfg) -> "TkETOptimisePass":
        return cls(level=int(cfg.get("level", 1)))
    
    def to_config(self):
        return {"level" : self.level}

    def run(self, ctx: QPassContext) -> QPassContext:
        # tket imports only inside run (so core env doesn't need them)
        from pytket.qasm import circuit_from_qasm_str, circuit_to_qasm_str
        from pytket.passes import (
            FullPeepholeOptimise,
            SynthesiseTket,
            RemoveRedundancies
        )

        # Expect QASM2 here
        passes = []
        if self.level <= 1:
            passes.append(FullPeepholeOptimise())
        else:
            passes += [RemoveRedundancies(),SynthesiseTket(), FullPeepholeOptimise(), RemoveRedundancies() ]
        super().__init__(passes)
        ctx = super().run(ctx)
        return ctx
