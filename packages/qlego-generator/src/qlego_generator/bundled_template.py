from typing import Optional
from qlego.registry import PassRegistry
from qlego_generator.template import Template
from qlego.qpass import QPassContext

BUNDLE_STAGES = [
    "Bundle: 1q Simplification",
    "Bundle: Commutation & Algebraic",
    "Bundle: Clifford-Aware",
    "Bundle: Block Collection + Synthesis",
    "Bundle: Identity & Cleanup",
    "Bundle: Measurement & Terminal Cleanup"
]

class RoleBasedCompilationTemplate(Template):
    """
    A compilation sequence where the optimization stage is divided into 
    predictable sequential role bundles. Instead of a single "Optimization" 
    stage, optimization flows explicitly through 1q -> Commutation -> Synthesis -> etc.
    
    Usage:
        t = RoleBasedCompilationTemplate(
            name="My Hybrid Pipeline",
            bundle_passes={
                "Bundle: 1q Simplification": Optimize1qGatesPass(),
                "Bundle: Commutation & Algebraic": CommutativeCancellationPass(),
                ...
            },
            initialization=PresetInitPass(),
            layout=PresetLayoutPass(),
            routing=PresetRoutingPass(),
            translation=PresetTranslationPass(),
        )
        ctx = t.compile(ctx=ctx)
    """

    def __init__(self, name: str, bundle_passes: dict, **kwargs):
        """
        Args:
            name: Readable name for this specific pipeline configuration
            bundle_passes: dict mapping a category from BUNDLE_STAGES 
                           to exactly one instantiated QLego optimization pass.
            **kwargs: Standard non-optimization stage passes (initialization, layout, routing, etc.)
        """
        stages = ["Initialization", "Layout", "Routing"] + BUNDLE_STAGES + ["Translation", "Scheduling"]
        super().__init__(name=name, stages=stages)
        
        self.pass_mapping = {}

        # Fill the non-optimization standard stages
        for stage in ["Initialization", "Layout", "Routing", "Translation", "Scheduling"]:
            kwarg_key = stage.lower()
            if kwarg_key in kwargs:
                pass_instance = kwargs[kwarg_key]
                if pass_instance is not None:
                    if isinstance(pass_instance, list):
                        for p in pass_instance:
                            self.add_pass(stage, p)
                    else:
                        self.add_pass(stage, pass_instance)

        # Fill the explicit bundle slots
        for category, pass_inst in bundle_passes.items():
            if category in BUNDLE_STAGES and pass_inst is not None:
                self.add_pass(category, pass_inst)

    @staticmethod
    def get_bundle_categories():
        """Return the standard sequential bundle stages."""
        return BUNDLE_STAGES
