"""Unified modifier system integrating all plugin types.

This module provides a unified interface for all ROM modifications,
including system-level plugins and APK-level plugins.
"""

from pathlib import Path
from typing import List, Optional

from src.core.modifiers.base_modifier import BaseModifier
from src.core.modifiers.plugin_system import PluginManager, ModifierPlugin
from src.core.modifiers.plugins import (
    FileReplacementPlugin,
    PermissionMigrationPlugin,
    ZipOverridePlugin,
    FeatureHandlerPlugin,
    DolbyFixPlugin,
    AIMemoryPlugin,
    VNDKFixPlugin,
    DeviceOverridePlugin,
)


class UnifiedModifier(BaseModifier):
    """Unified modifier handling both system and APK modifications.

    This provides a single entry point for all ROM modifications:
    - System-level: File replacements, features, etc.
    - APK-level: Individual APK patches (if applicable)
    """

    def __init__(
        self,
        context,
        enable_apk_mods: bool = True,
        dry_run: bool = False,
        max_workers: int = 4,
    ):
        super().__init__(context, "UnifiedModifier")

        # System-level plugin manager
        self.system_manager = PluginManager(
            context, self.logger, dry_run=dry_run, max_workers=max_workers
        )

        self._dry_run = dry_run
        self._register_plugins()

    def _register_plugins(self):
        """Register all default plugins."""
        self.logger.debug("Registering system-level plugins...")

        # Register plugins in order of priority
        plugins_to_register = [
            # Priority 10: File replacements and overrides
            FileReplacementPlugin,
            ZipOverridePlugin,
            # Priority 20: Permission and configuration migration
            PermissionMigrationPlugin,
            # Priority 30: Feature handling
            FeatureHandlerPlugin,
            # Priority 40: Device-specific fixes
            DolbyFixPlugin,
            AIMemoryPlugin,
            VNDKFixPlugin,
            DeviceOverridePlugin,
        ]

        for plugin_cls in plugins_to_register:
            try:
                self.system_manager.register(plugin_cls)
                self.logger.debug(f"Registered plugin: {plugin_cls.__name__}")
            except Exception as e:
                self.logger.warning(
                    f"Could not register plugin {plugin_cls.__name__}: {e}"
                )

        # Log registered plugins
        registered_plugins = self.system_manager.list_plugins()
        if len(registered_plugins) == 0:
            self.logger.warning("No plugins registered in system manager")
        else:
            self.logger.debug(
                f"Registered {len(registered_plugins)} system-level plugins: "
                f"{[p.name for p in registered_plugins]}"
            )

    def run(self, phases: Optional[List[str]] = None) -> bool:
        """Execute all modifications.

        Args:
            phases: Optional list of phases to run ('system', 'apk')
                   If None, runs all phases.

        Returns:
            bool: True if all phases succeeded
        """
        phases = phases or ["system"]
        all_success = True

        # Phase 1: System-level modifications
        if "system" in phases:
            self.logger.info("=" * 60)
            self.logger.info("PHASE 1: System-Level Modifications")
            self.logger.info("=" * 60)

            self.logger.info("Executing system-level plugins...")
            results = self.system_manager.execute()

            success = sum(1 for r in results.values() if r is True)
            failed = sum(1 for r in results.values() if r is False)
            skipped = sum(1 for r in results.values() if r is None)

            self.logger.info(
                f"System modifications: {success} succeeded, "
                f"{failed} failed, {skipped} skipped"
            )

            if failed > 0:
                all_success = False

        return all_success

    def add_system_plugin(self, plugin_class, **kwargs):
        """Add a custom system-level plugin."""
        self.system_manager.register(plugin_class, **kwargs)
        return self

    def enable_system_plugin(self, name: str, enabled: bool = True):
        """Enable/disable a system plugin."""
        self.system_manager.enable_plugin(name, enabled)
        return self

    def list_plugins(self) -> dict:
        """List all registered plugins."""
        return {
            "system": self.system_manager.list_plugins(),
        }


# Backward compatibility: SystemModifier still works as before
class SystemModifier(BaseModifier):
    """Handles system-level ROM modifications using plugins.

    Note: This is now a thin wrapper around UnifiedModifier for
    backward compatibility. Consider using UnifiedModifier directly.
    """

    def __init__(self, context):
        super().__init__(context, "SystemModifier")
        self._unified = UnifiedModifier(context, enable_apk_mods=False)

    def run(self) -> bool:
        """Execute system modifications."""
        return self._unified.run(phases=["system"])

    def add_plugin(self, plugin_class, **kwargs):
        """Add a custom plugin."""
        self._unified.add_system_plugin(plugin_class, **kwargs)
        return self

    def enable_plugin(self, name: str, enabled: bool = True):
        """Enable/disable a plugin."""
        self._unified.enable_system_plugin(name, enabled)
        return self

    def list_plugins(self):
        """List all registered plugins."""
        return self._unified.list_plugins()["system"]
