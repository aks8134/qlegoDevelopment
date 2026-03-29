import importlib
import pkgutil
import inspect
from typing import Dict, List, Type, Optional, Callable

# Format: {category: {f"{plugin_name}_{pass_name}": PassClass}}
_REGISTRY: Dict[str, Dict[str, Type]] = {}

class PassRegistry:
    """Central registry for discovering and fetching QLego compiler passes."""
    
    @classmethod
    def register(cls, category: str, pass_class: Type, plugin_name: str) -> None:
        if category not in _REGISTRY:
            _REGISTRY[category] = {}
            
        pass_name = pass_class.__name__
        key = f"{plugin_name}_{pass_name}"
        _REGISTRY[category][key] = pass_class
        
    @classmethod
    def get_passes_by_category(cls, category: str) -> Dict[str, Type]:
        """Returns all registered passes for a given category across plugins."""
        return _REGISTRY.get(category, {})

    @classmethod
    def get_plugin_passes(cls, plugin_name: str, category: Optional[str] = None) -> Dict[str, Type]:
        """Returns registered passes for a specific plugin, optionally filtered by category."""
        passes = {}
        prefix = f"{plugin_name}_"
        
        if category:
            cat_passes = _REGISTRY.get(category, {})
            return {k: v for k, v in cat_passes.items() if k.startswith(prefix)}
            
        for cat, cat_passes in _REGISTRY.items():
            passes.update({k: v for k, v in cat_passes.items() if k.startswith(prefix)})
        return passes
        
    @classmethod
    def get_all_categories(cls) -> List[str]:
        return list(_REGISTRY.keys())


def register_pass(category: str) -> Callable:
    """
    Decorator to register a QLego pass.
    Example: @register_pass("Layout")
    """
    def decorator(cls: Type) -> Type:
        # Resolve which plugin package this pass belongs to via standard __module__ tracking
        module_path = cls.__module__
        # e.g., 'qlego_qiskit.adapter.passes' -> 'qlego-qiskit'
        plugin_name = module_path.split('.')[0].replace("_", "-")
        
        PassRegistry.register(category, cls, plugin_name)
        return cls
    return decorator
