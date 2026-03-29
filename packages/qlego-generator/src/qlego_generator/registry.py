import os
import json
import importlib
import importlib.util
import sys

def aggregate_from_environment(config_path: str = "envs/env_config.json") -> None:
    """
    Dynamically imports the `adapter.passes` module of all tracked plugins to trigger 
    their local @register_pass decorators in the driver environment.
    """
    if not os.path.exists(config_path):
        return
        
    with open(config_path, "r") as f:
        env_config = json.load(f)
        
    for plugin in env_config.keys():
        # Standardize plugin name (e.g. qlego-qiskit -> qlego_qiskit)
        module_name = plugin.replace("-", "_")
        pass_adapter = f"{module_name}.adapter.passes"
        try:
            importlib.import_module(pass_adapter)
        except ImportError:
            pass

def aggregate_from_script(script_path: str) -> None:
    """
    Dynamically imports a custom python script by file path to trigger its 
    local @register_pass decorators, adding them to the global PassRegistry.
    """
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"Script not found: {script_path}")
        
    module_name = os.path.splitext(os.path.basename(script_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        # Ensure the module is registered in sys.modules so imports within it work correctly
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
