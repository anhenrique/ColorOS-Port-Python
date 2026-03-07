"""ColorOS ROM Modifiers - Plugin-based modification system.

This package provides a flexible plugin architecture for ROM modifications,
adapted from the HyperOS Port project.
"""

from src.core.modifiers.base_modifier import BaseModifier
from src.core.modifiers.plugin_system import (
    ModifierPlugin,
    PluginManager,
    ModifierRegistry,
)
from src.core.modifiers.transaction import TransactionManager
from src.core.modifiers.unified_modifier import UnifiedModifier
from src.core.modifiers.framework_modifier import FrameworkModifier
from src.core.modifiers.firmware_modifier import FirmwareModifier

__all__ = [
    "BaseModifier",
    "ModifierPlugin",
    "PluginManager",
    "ModifierRegistry",
    "TransactionManager",
    "UnifiedModifier",
    "FrameworkModifier",
    "FirmwareModifier",
]
