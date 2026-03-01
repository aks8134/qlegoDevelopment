from qlego.qpass import QPassContext
from qlego_bqskit.adapter.passes import BQSKITPass


class BqskitInit(BQSKITPass):
    def __init__(self):
        pass

    def run(self, ctx):
        from bqskit.passes import UnfoldPass, CompressPass, GroupSingleQuditGatePass

        # “init / normalize” stage: unfold higher-level gates and tidy.
        super().__init__([UnfoldPass(), GroupSingleQuditGatePass(), CompressPass()])
        return super().run(ctx)


class BqskitPlacement(BQSKITPass):
    def __init__(self):
        pass

    def run(self, ctx):
        from bqskit.passes import GeneralizedSabreLayoutPass, ApplyPlacement

        # Layout decides a placement; ApplyPlacement commits it into the circuit.
        # (Layout is often what you want for “placement” semantics.)
        super().__init__([GeneralizedSabreLayoutPass(), ApplyPlacement()])
        return super().run(ctx)


class BqskitRouting(BQSKITPass):
    def __init__(self):
        pass

    def run(self, ctx):
        from bqskit.passes import GeneralizedSabreRoutingPass

        # Routing inserts swaps / rewrites so 2Q ops respect connectivity.
        super().__init__([GeneralizedSabreRoutingPass()])
        return super().run(ctx)


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


class BqskitOptimisePass(BQSKITPass):
    name = "BQSKit Optimise Pass"

    def __init__(self, level: int = 1):
        self.level = int(level)

    @classmethod
    def from_config(cls, cfg) -> "BqskitOptimisePass":
        return cls(
            level=int(cfg.get("level", 1)),
        )

    def to_config(self):
        return {"level": self.level}

    def run(self, ctx: QPassContext) -> QPassContext:
        from bqskit.passes import (
            QuickPartitioner,
            ScanPartitioner,
            LEAPSynthesisPass,
            QSearchSynthesisPass,
            ScanningGateRemovalPass,
            CompressPass,
        )

        # A reasonable “levels” mapping:
        # - L1: lightweight cleanup + small synthesis
        # - L2+: more aggressive partition + synthesis + cleanup
        passes = []

        if self.level <= 1:
            passes += [
                CompressPass(),
                QuickPartitioner(block_size=3),
                LEAPSynthesisPass(),
                ScanningGateRemovalPass(),
                CompressPass(),
            ]
        else:
            passes += [
                CompressPass(),
                ScanPartitioner(block_size=4),
                QSearchSynthesisPass(),
                ScanningGateRemovalPass(),
                CompressPass(),
            ]

        super().__init__(passes)
        return super().run(ctx)
