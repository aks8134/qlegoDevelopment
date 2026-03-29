from typing import List, Dict, Any, Optional
from qlego.qpass import QPipeline, QPassContext

class Template:
    """
    A Template defines a specific flow of compilation stages.
    It utilizes QPipeline under the hood to execute passes.
    """
    def __init__(self, name: str, stages: List[str]):
        """
        Initialize the Template with a name and an ordered list of stages.
        Stages can be repeated (e.g., Optimization before and after Routing).
        """
        self.name = name
        self.stages = stages
        self.pass_mapping: Dict[str, List[Any]] = {}

    def add_pass(self, stage_name: str, pass_instance: Any):
        """
        Add a pass instance to a specific stage type.
        If the stage type appears multiple times in the flow, these passes
        will be executed multiple times.
        """
        if stage_name not in self.stages:
            raise ValueError(f"Stage '{stage_name}' is not a valid stage in template '{self.name}'. "
                             f"Valid stages are: {self.stages}")
        if stage_name not in self.pass_mapping:
            self.pass_mapping[stage_name] = []
        self.pass_mapping[stage_name].append(pass_instance)

    def compile(self, qasm_in: str = None, ctx: Optional[QPassContext] = None) -> QPassContext:
        """
        Execute the template using a QPipeline sequentially through all defined stages.
        """
        flat_passes = []
        for stage in self.stages:
            if stage in self.pass_mapping:
                # Add the passes for this stage type to the flow
                flat_passes.extend(self.pass_mapping[stage])
                
        pipeline = QPipeline(flat_passes)
        
        if qasm_in is None:
            if ctx is not None and getattr(ctx, "qasm", None) is not None:
                qasm_in = ctx.qasm
            else:
                qasm_in = ""
                
        return pipeline.run(qasm_in, ctx=ctx)


class DefaultCompilationTemplate(Template):
    """
    A standard compilation template which defines the common flow:
    Initialization -> Layout -> Routing -> Optimization -> Translation -> Scheduling
    """
    def __init__(self, **kwargs):
        """
        Initialize with the standard compilation flow.
        You can pass pass instances directly using lowercase stage names:
        e.g., DefaultCompilationTemplate(initialization=MyInitPass(), layout=MyLayoutPass())
        """
        stages = ["Initialization", "Layout", "Routing", "Optimization", "Translation", "Scheduling"]
        super().__init__(name="DefaultCompilationTemplate", stages=stages)
        
        for stage in stages:
            kwarg_key = stage.lower()
            if kwarg_key in kwargs:
                pass_instance = kwargs[kwarg_key]
                if pass_instance is not None:
                    # If the user provides a list of passes for a stage, add all
                    if isinstance(pass_instance, list):
                        for p in pass_instance:
                            self.add_pass(stage, p)
                    else:
                        self.add_pass(stage, pass_instance)
