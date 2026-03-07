import logging
import pkgutil
import importlib
from typing import Dict, List, Type, Any, Optional
from pathlib import Path

from src.modules.base import BaseModule

class ModuleRegistry:
    """Registry to manage feature modules."""

    def __init__(self, context: Any, logger: Optional[logging.Logger] = None):
        self.ctx = context
        self.logger = logger or logging.getLogger("ModuleRegistry")
        self.modules: Dict[str, BaseModule] = {}

    def register(self, module_class: Type[BaseModule], **kwargs) -> "ModuleRegistry":
        """Register a module class."""
        instance = module_class(self.ctx, **kwargs)
        self.modules[instance.name] = instance
        self.logger.debug(f"Registered module: {instance.name} (Priority: {instance.priority})")
        return self

    def discover_and_register(self, modules_package: str = "src.modules") -> "ModuleRegistry":
        """Auto-discover and register all modules in a package."""
        package = importlib.import_module(modules_package)
        for _, name, is_pkg in pkgutil.iter_modules(package.__path__):
            if is_pkg:
                # Recursively discover subpackages if needed
                continue
            
            if name in ["base", "registry", "__init__"]:
                continue

            module_name = f"{modules_package}.{name}"
            try:
                mod = importlib.import_module(module_name)
                for item_name in dir(mod):
                    item = getattr(mod, item_name)
                    if (isinstance(item, type) and 
                        issubclass(item, BaseModule) and 
                        item is not BaseModule):
                        self.register(item)
            except Exception as e:
                self.logger.error(f"Failed to load module {module_name}: {e}")
        
        return self

    def run_all(self) -> Dict[str, bool]:
        """Execute all enabled modules in order of priority."""
        sorted_modules = sorted(self.modules.values(), key=lambda m: m.priority)
        results = {}

        self.logger.info(f"Running {len(sorted_modules)} feature modules...")
        for module in sorted_modules:
            if not module.enabled:
                self.logger.debug(f"Module {module.name} is disabled, skipping.")
                continue

            try:
                self.logger.info(f"==> Running Module: {module.name} ({module.description})")
                success = module.run()
                results[module.name] = success
                if success:
                    self.logger.debug(f"Module {module.name} completed successfully.")
                else:
                    self.logger.warning(f"Module {module.name} returned failure.")
            except Exception as e:
                self.logger.error(f"Module {module.name} failed with exception: {e}", exc_info=True)
                results[module.name] = False

        return results

# Global registry helper could be initialized per-context
