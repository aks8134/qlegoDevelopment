"""
A custom external script demonstrating new PassRegistry hooks.
"""
from qlego.registry import register_pass
from qlego.qpass import QPass

@register_pass("Optimization")
class MyCustomPass(QPass):
    name = "Custom External Pass"
    def run(self, ctx):
        import sys
        print("Executing highly experimental external pass...", file=sys.stderr)
        return ctx
