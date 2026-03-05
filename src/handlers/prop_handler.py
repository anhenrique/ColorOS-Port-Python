"""
Build Property Handler Module

Handles modifications to build.prop files across multiple partitions.
"""

from pathlib import Path
from typing import Dict, Any, List, Set, Union
import logging

from .base import BaseHandler
from .conditions import ConditionContext, condition_engine


class BuildPropHandler(BaseHandler):
    """
    Handler for build.prop modifications.

    Supports adding, updating, and removing properties from
    various partition build.prop files.
    """

    # Supported partitions
    PARTITIONS = [
        "system",
        "system_ext",
        "product",
        "vendor",
        "odm",
        "my_product",
        "my_manifest",
    ]

    # Default build.prop paths for each partition
    DEFAULT_PATHS = {
        "system": ["build.prop", "system/build.prop"],
        "system_ext": ["build.prop", "etc/build.prop"],
        "product": ["build.prop", "etc/build.prop"],
        "vendor": ["build.prop", "etc/build.prop"],
        "odm": ["build.prop", "etc/build.prop"],
        "my_product": ["build.prop", "etc/build.prop"],
        "my_manifest": ["build.prop"],
    }

    def __init__(self):
        super().__init__()
        self.condition_engine = condition_engine

    def can_handle(self, config: Dict[str, Any]) -> bool:
        """Check if config contains build property definitions"""
        return any(
            key in config for key in ["build_props", "props_add", "props_remove"]
        )

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate build property configuration"""
        errors = []

        for key in ["build_props", "props_add"]:
            if key not in config:
                continue

            props_map = config[key]
            if not isinstance(props_map, dict):
                errors.append(f"{key} must be a dictionary")
                continue

            for partition, props in props_map.items():
                if partition not in self.PARTITIONS:
                    errors.append(f"Unknown partition '{partition}' in {key}")

                if not isinstance(props, dict):
                    errors.append(f"Properties for {partition} must be a dictionary")

        # Validate props_remove
        if "props_remove" in config:
            props_remove = config["props_remove"]
            if not isinstance(props_remove, list):
                errors.append("props_remove must be a list")
            else:
                for i, prop in enumerate(props_remove):
                    if isinstance(prop, dict):
                        if "name" not in prop:
                            errors.append(f"props_remove[{i}]: missing 'name' field")
                    elif not isinstance(prop, str):
                        errors.append(f"props_remove[{i}]: must be string or dict")

        return errors

    def apply(self, config: Dict[str, Any], context: Any) -> None:
        """Apply build property modifications"""
        condition_ctx = self._build_condition_context(context)

        # Process additions/updates
        props_map = config.get("build_props") or config.get("props_add", {})

        for partition, props in props_map.items():
            if partition not in self.PARTITIONS:
                self.logger.warning(f"Unknown partition: {partition}, skipping")
                continue

            prop_files = self._find_prop_files(context, partition)

            if not prop_files:
                self.logger.warning(f"No build.prop found for partition: {partition}")
                continue

            for prop_file in prop_files:
                self._apply_props_to_file(prop_file, props, condition_ctx)

        # Process removals
        if "props_remove" in config:
            self._process_removals(config["props_remove"], context, condition_ctx)

    def _find_prop_files(self, context: Any, partition: str) -> List[Path]:
        """Find all build.prop files for a partition"""
        target_dir = context.target_dir / partition
        prop_files = []

        paths = self.DEFAULT_PATHS.get(partition, ["build.prop"])

        for path in paths:
            full_path = target_dir / path
            if full_path.exists():
                prop_files.append(full_path)

        return prop_files

    def _apply_props_to_file(
        self, prop_file: Path, props: Dict[str, Any], condition_ctx: ConditionContext
    ) -> None:
        """Apply properties to a single build.prop file"""
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()

        # Parse existing properties
        existing_props = {}
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, value = stripped.split("=", 1)
                existing_props[key.strip()] = {"value": value.strip(), "line": i}

        modified = False

        for key, value_config in props.items():
            # Parse value configuration
            if isinstance(value_config, dict):
                value = value_config.get("value", "")
                comment = value_config.get("comment", "")
                condition = value_config.get("condition")
            else:
                value = str(value_config)
                comment = ""
                condition = None

            # Check condition
            if condition:
                if not self.condition_engine.evaluate(condition, condition_ctx):
                    self.logger.debug(f"Skipping prop {key}: condition not met")
                    continue

            # Check if property exists
            if key in existing_props:
                # Update existing property
                line_idx = existing_props[key]["line"]
                old_value = existing_props[key]["value"]

                if old_value != value:
                    lines[line_idx] = f"{key}={value}"
                    modified = True
                    self.logger.info(f"Updated {key}: {old_value} -> {value}")

                # Add comment if present and not already there
                if comment:
                    prev_line_idx = line_idx - 1
                    if prev_line_idx >= 0:
                        prev_line = lines[prev_line_idx].strip()
                        if not prev_line.startswith("#") or comment not in prev_line:
                            lines.insert(line_idx, f"# {comment}")
                            modified = True
            else:
                # Add new property
                if comment:
                    lines.append(f"# {comment}")
                lines.append(f"{key}={value}")
                modified = True
                self.logger.info(f"Added prop: {key}={value}")

        if modified:
            prop_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _process_removals(
        self,
        props_remove: List[Union[str, Dict]],
        context: Any,
        condition_ctx: ConditionContext,
    ) -> None:
        """Process property removals"""
        for prop_config in props_remove:
            if isinstance(prop_config, dict):
                prop_name = prop_config["name"]
                force = prop_config.get("force", False)
                condition = prop_config.get("condition")
            else:
                prop_name = prop_config
                force = False
                condition = None

            # Check condition
            if condition:
                if not self.condition_engine.evaluate(condition, condition_ctx):
                    continue

            # Check baserom unless force mode
            if not force and hasattr(context, "baserom"):
                if self._prop_in_baserom(context, prop_name):
                    self.logger.info(
                        f"Prop {prop_name} exists in baserom, skipping removal"
                    )
                    continue

            # Remove from all partitions
            for partition in self.PARTITIONS:
                prop_files = self._find_prop_files(context, partition)
                for prop_file in prop_files:
                    self._remove_prop_from_file(prop_file, prop_name)

    def _remove_prop_from_file(self, prop_file: Path, prop_name: str) -> None:
        """Remove a property from a build.prop file"""
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        new_lines = []
        removed = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{prop_name}="):
                removed = True
                continue
            new_lines.append(line)

        if removed:
            prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            self.logger.info(f"Removed prop {prop_name} from {prop_file.name}")

    def _prop_in_baserom(self, context: Any, prop_name: str) -> bool:
        """Check if property exists in baserom"""
        if not hasattr(context, "baserom") or not context.baserom:
            return False

        for partition in self.PARTITIONS:
            baserom_dir = context.baserom.extracted_dir / partition
            if not baserom_dir.exists():
                continue

            for path in self.DEFAULT_PATHS.get(partition, ["build.prop"]):
                prop_file = baserom_dir / path
                if not prop_file.exists():
                    continue

                try:
                    content = prop_file.read_text(encoding="utf-8", errors="ignore")
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped.startswith(f"{prop_name}="):
                            return True
                except:
                    pass

        return False

    def _build_condition_context(self, context: Any) -> ConditionContext:
        """Build condition context from build context"""
        return ConditionContext(
            base_android_version=int(getattr(context, "base_android_version", 0) or 0),
            port_android_version=int(getattr(context, "port_android_version", 0) or 0),
            base_product_device=getattr(context, "base_product_device", ""),
            port_product_device=getattr(context, "port_product_device", ""),
            port_rom_version=getattr(context, "target_rom_version", ""),
            port_is_coloros=getattr(context, "port_is_coloros", False),
            port_is_coloros_global=getattr(context, "port_is_coloros_global", False),
            port_is_oos=getattr(context, "port_is_oos", False),
            port_is_realme_ui=getattr(context, "port_is_realme_ui", False),
            base_regionmark=getattr(context, "base_regionmark", ""),
            port_area=getattr(context, "port_area", ""),
            port_brand=getattr(context, "port_brand", ""),
        )
