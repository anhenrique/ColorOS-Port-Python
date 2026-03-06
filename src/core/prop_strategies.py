"""
Property modification strategies - Implements configuration-driven prop modification.
"""

import re
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from string import Formatter

logger = logging.getLogger(__name__)


class PropStrategy(ABC):
    """Abstract base class for property modification strategies."""
    
    def __init__(self, config: Dict[str, Any], context: Any):
        self.config = config
        self.ctx = context
        self.name = config.get("name", self.__class__.__name__)
        self.priority = config.get("priority", 50)
        self.enabled = config.get("enabled", True)
    
    @abstractmethod
    def apply(self, target_dir: Path) -> bool:
        """
        Apply the strategy to the target directory.
        
        Returns:
            True if successful, False otherwise
        """
        pass
    
    def check_condition(self) -> bool:
        """Check if strategy's condition is satisfied."""
        condition = self.config.get("condition")
        if not condition:
            return True
        
        for key, expected in condition.items():
            actual = self._get_context_value(key)
            if actual is None:
                return False
            
            # Handle comparison operators
            if key.endswith("_lt"):
                if actual >= expected:
                    return False
            elif key.endswith("_lte"):
                if actual > expected:
                    return False
            elif key.endswith("_gt"):
                if actual <= expected:
                    return False
            elif key.endswith("_gte"):
                if actual < expected:
                    return False
            elif key.endswith("_ne"):
                if actual == expected:
                    return False
            elif actual != expected:
                return False
        
        return True
    
    def _get_context_value(self, key: str) -> Any:
        """Get value from context using dot notation or special mappings."""
        # Handle special key mappings
        mappings = {
            "port_device_code": lambda: self.ctx.portrom.device_code,
            "port_product_model": lambda: self.ctx.portrom.product_model,
            "port_product_name": lambda: self.ctx.portrom.product_name,
            "port_product_device": lambda: self.ctx.portrom.product_device,
            "port_vendor_device": lambda: self.ctx.portrom.vendor_device,
            "port_vendor_model": lambda: self.ctx.portrom.vendor_model,
            "port_vendor_brand": lambda: self.ctx.portrom.vendor_brand,
            "port_android_version": lambda: int(self.ctx.portrom.android_version or 0),
            "port_is_coloros_global": lambda: self.ctx.portrom.is_coloros_global,
            "base_device_code": lambda: self.ctx.baserom.device_code,
            "base_product_model": lambda: self.ctx.baserom.product_model,
            "base_product_name": lambda: self.ctx.baserom.product_name,
            "base_product_device": lambda: self.ctx.baserom.product_device,
            "base_vendor_device": lambda: self.ctx.baserom.vendor_device,
            "base_vendor_model": lambda: self.ctx.baserom.vendor_model,
            "base_vendor_brand": lambda: self.ctx.baserom.vendor_brand,
            "base_market_name": lambda: self.ctx.baserom.market_name,
            "base_market_enname": lambda: self.ctx.baserom.market_enname,
            "base_lcd_density": lambda: self.ctx.baserom.lcd_density,
            "target_display_id": lambda: self.ctx.target_display_id,
        }
        
        if key in mappings:
            try:
                return mappings[key]()
            except (AttributeError, TypeError, ValueError):
                return None
        
        # Try direct attribute access
        try:
            return getattr(self.ctx, key, None)
        except:
            return None


class TimezoneStrategy(PropStrategy):
    """Strategy for setting timezone property."""
    
    def apply(self, target_dir: Path) -> bool:
        key = self.config["config"]["key"]
        value = self.config["config"]["value"]
        
        modified_count = 0
        for prop_file in target_dir.rglob("build.prop"):
            if self._update_prop_file(prop_file, key, value):
                modified_count += 1
        
        logger.debug(f"TimezoneStrategy: Modified {modified_count} files")
        return True
    
    def _update_prop_file(self, prop_file: Path, key: str, value: str) -> bool:
        if not prop_file.exists():
            return False
        
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        if key not in content:
            return False
        
        new_content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        if new_content != content:
            prop_file.write_text(new_content, encoding="utf-8")
            return True
        return False


class GlobalReplacementStrategy(PropStrategy):
    """Strategy for global string replacements across all build.prop files."""
    
    def apply(self, target_dir: Path) -> bool:
        mappings = self.config["config"]["mappings"]
        
        # Build replacement pairs
        replacements = []
        for mapping in mappings:
            old_val = self._get_context_value(mapping["from"])
            new_val = self._get_context_value(mapping["to"])
            if old_val and new_val and old_val != new_val:
                replacements.append((old_val, new_val))
        
        if not replacements:
            logger.debug("GlobalReplacementStrategy: No replacements needed")
            return True
        
        modified_count = 0
        for prop_file in target_dir.rglob("build.prop"):
            if "system_dlkm" in str(prop_file) or "odm_dlkm" in str(prop_file):
                continue
            
            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            original = content
            
            for old_val, new_val in replacements:
                content = content.replace(old_val, new_val)
            
            if content != original:
                prop_file.write_text(content, encoding="utf-8")
                modified_count += 1
        
        logger.debug(f"GlobalReplacementStrategy: Modified {modified_count} files")
        return True


class DisplayIdStrategy(PropStrategy):
    """Strategy for updating display ID."""
    
    def apply(self, target_dir: Path) -> bool:
        key = self.config["config"]["key"]
        value = self._get_context_value(self.config["config"]["source"])
        
        if not value:
            logger.debug("DisplayIdStrategy: No display ID available")
            return True
        
        for prop_file in target_dir.rglob("build.prop"):
            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            if key in content:
                new_content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
                if new_content != content:
                    prop_file.write_text(new_content, encoding="utf-8")
        
        return True


class RegionLockStrategy(PropStrategy):
    """Strategy for disabling region lock."""
    
    def apply(self, target_dir: Path) -> bool:
        properties = self.config["config"]["properties"]
        
        for prop_file in target_dir.rglob("build.prop"):
            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            modified = False
            
            for prop in properties:
                key = prop["key"]
                value = prop["value"]
                if key in content:
                    content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
                    modified = True
            
            if modified:
                prop_file.write_text(content, encoding="utf-8")
        
        return True


class WatermarkStrategy(PropStrategy):
    """Strategy for adding watermark to ROM version."""
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        target_key = cfg["target_key"]
        template = cfg["template"]
        author = cfg.get("author", "BT")
        skip_if_contains = cfg.get("skip_if_contains", "")
        
        # Find target files
        my_product = target_dir / "my_product"
        if not my_product.exists():
            return True
        
        prop_main = my_product / "build.prop"
        prop_bruce = my_product / "etc" / "bruce" / "build.prop"
        
        target_file = prop_main if prop_main.exists() else prop_bruce
        if not target_file.exists():
            return True
        
        value = self._read_prop_value(target_file, target_key)
        if not value or skip_if_contains in value:
            return True
        
        new_value = template.format(value=value, author=author)
        self._add_or_replace_prop(target_file, target_key, new_value)
        
        return True
    
    def _read_prop_value(self, file_path: Path, key: str) -> Optional[str]:
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and line.startswith(f"{key}="):
                        return line.split("=", 1)[1].strip()
        except:
            pass
        return None
    
    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding="utf-8")
        
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class MarketNameStrategy(PropStrategy):
    """Strategy for setting market names."""
    
    def apply(self, target_dir: Path) -> bool:
        my_product = target_dir / "my_product"
        if not my_product.exists():
            return True
        
        bruce_prop = my_product / "etc" / "bruce" / "build.prop"
        
        # Check manifest if configured
        if self.config["config"].get("check_manifest", True):
            manifest_prop = self.ctx.baserom.extracted_dir / "my_manifest" / "build.prop"
            manifest_props = self._read_props_to_dict(manifest_prop)
        else:
            manifest_props = {}
        
        for prop_config in self.config["config"]["properties"]:
            key = prop_config["key"]
            source = prop_config["source"]
            
            # Skip if in manifest
            key_variants = [key.replace("ro.vendor.", "ro."), key]
            if any(v in manifest_props for v in key_variants):
                continue
            
            value = self._get_context_value(source)
            if value:
                self._add_or_replace_prop(bruce_prop, key, value)
        
        return True
    
    def _read_props_to_dict(self, file_path: Path) -> Dict[str, str]:
        props = {}
        if not file_path.exists():
            return props
        try:
            with open(file_path, "r", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        props[key.strip()] = val.strip()
        except:
            pass
        return props
    
    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding="utf-8")
        
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class MagicModelStrategy(PropStrategy):
    """Strategy for setting magic model properties."""
    
    def apply(self, target_dir: Path) -> bool:
        my_product = target_dir / "my_product"
        if not my_product.exists():
            return True
        
        bruce_prop = my_product / "etc" / "bruce" / "build.prop"
        
        device_code = self.ctx.baserom.device_code or ""
        product_model = self.ctx.baserom.product_model or ""
        
        for prop_config in self.config["config"]["properties"]:
            key = prop_config["key"]
            template = prop_config["template"]
            value = template.format(device_code=device_code, product_model=product_model)
            self._add_or_replace_prop(bruce_prop, key, value)
        
        return True
    
    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding="utf-8")
        
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class LcdDensityStrategy(PropStrategy):
    """Strategy for setting LCD density."""
    
    def apply(self, target_dir: Path) -> bool:
        key = self.config["config"]["key"]
        value = self._get_context_value(self.config["config"]["source"])
        
        if not value:
            return True
        
        target_file = self.config["config"].get("target_file", "my_product/build.prop")
        prop_file = target_dir / target_file
        
        if prop_file.exists():
            self._add_or_replace_prop(prop_file, key, value)
        
        return True
    
    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class SystemExtBrandStrategy(PropStrategy):
    """Strategy for setting system_ext brand."""
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        file_path = target_dir / cfg["file"]
        key = cfg["key"]
        value = self._get_context_value(cfg["source"])
        
        if not value or not file_path.exists():
            return True
        
        if cfg.get("transform") == "lowercase":
            value = value.lower()
        
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        file_path.write_text(content, encoding="utf-8")
        
        return True


class FingerprintStrategy(PropStrategy):
    """Strategy for regenerating build fingerprint."""
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        priority_partitions = cfg["priority_partitions"]
        components = cfg["components"]
        targets = cfg["targets"]
        
        # Read component values
        values = {}
        for name, comp_config in components.items():
            values[name] = self._get_prop_from_partitions(
                target_dir, 
                priority_partitions, 
                comp_config["key"],
                comp_config.get("default", "")
            )
        
        # Construct fingerprint
        fingerprint = f"{values['brand']}/{values['name']}/{values['device']}:{values['version']}/{values['build_id']}/{values['incremental']}:{values['type']}/{values['tags']}"
        description = f"{values['name']}-{values['type']} {values['version']} {values['build_id']} {values['incremental']} {values['tags']}"
        
        logger.info(f"New Fingerprint: {fingerprint}")
        
        # Build replacement mapping
        replacements = {
            "ro.build.fingerprint=": f"ro.build.fingerprint={fingerprint}",
            "ro.bootimage.build.fingerprint=": f"ro.bootimage.build.fingerprint={fingerprint}",
            "ro.system.build.fingerprint=": f"ro.system.build.fingerprint={fingerprint}",
            "ro.product.build.fingerprint=": f"ro.product.build.fingerprint={fingerprint}",
            "ro.system_ext.build.fingerprint=": f"ro.system_ext.build.fingerprint={fingerprint}",
            "ro.vendor.build.fingerprint=": f"ro.vendor.build.fingerprint={fingerprint}",
            "ro.odm.build.fingerprint=": f"ro.odm.build.fingerprint={fingerprint}",
            "ro.build.description=": f"ro.build.description={description}",
            "ro.system.build.description=": f"ro.system.build.description={description}"
        }
        
        # Apply to all build.prop files
        for prop_file in target_dir.rglob("build.prop"):
            self._apply_replacements(prop_file, replacements)
        
        return True
    
    def _get_prop_from_partitions(self, target_dir: Path, partitions: List[str], key: str, default: str) -> str:
        for part in partitions:
            for prop_file in (target_dir / part).rglob("build.prop"):
                try:
                    with open(prop_file, 'r', errors='ignore') as f:
                        for line in f:
                            if line.strip().startswith(f"{key}="):
                                return line.split("=", 1)[1].strip()
                except:
                    pass
        return default
    
    def _apply_replacements(self, prop_file: Path, replacements: Dict[str, str]):
        try:
            with open(prop_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        except:
            return
        
        new_lines = []
        file_changed = False
        
        for line in lines:
            original = line
            stripped = line.strip()
            replaced = False
            
            for prefix, new_val in replacements.items():
                if stripped.startswith(prefix):
                    if original.strip() != new_val:
                        new_lines.append(new_val + "\n")
                        file_changed = True
                    else:
                        new_lines.append(original)
                    replaced = True
                    break
            
            if not replaced:
                new_lines.append(original)
        
        if file_changed:
            with open(prop_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            logger.debug(f"Updated fingerprint in {prop_file}")


# Strategy registry
STRATEGY_REGISTRY: Dict[str, type] = {
    "timezone": TimezoneStrategy,
    "global_replacement": GlobalReplacementStrategy,
    "display_id": DisplayIdStrategy,
    "region_lock": RegionLockStrategy,
    "watermark": WatermarkStrategy,
    "market_name": MarketNameStrategy,
    "magic_model": MagicModelStrategy,
    "lcd_density": LcdDensityStrategy,
    "system_ext_brand": SystemExtBrandStrategy,
    "fingerprint": FingerprintStrategy,
}


def create_strategy(config: Dict[str, Any], context: Any) -> Optional[PropStrategy]:
    """Factory function to create strategy instances from config."""
    name = config.get("name")
    if not name:
        return None
    
    strategy_class = STRATEGY_REGISTRY.get(name)
    if not strategy_class:
        logger.warning(f"Unknown strategy: {name}")
        return None
    
    return strategy_class(config, context)


class PropCopyStrategy(PropStrategy):
    """
    Generic strategy for copying properties from source to target files.
    Supports reading from baserom partitions and writing to multiple target partitions.
    """
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        props = cfg.get("properties", [])
        
        for prop_config in props:
            key = prop_config["key"]
            source_partitions = prop_config.get("source_partitions", ["my_manifest"])
            target_partitions = prop_config.get("target_partitions", ["vendor", "product", "system"])
            default_value = prop_config.get("default")
            
            # Read value from baserom source partitions
            value = self._read_from_baserom(source_partitions, key)
            
            if not value and default_value:
                value = default_value
            
            if not value:
                logger.warning(f"PropCopyStrategy: Could not find {key} in baserom")
                continue
            
            # Write to target partitions
            written = 0
            for part in target_partitions:
                part_dir = target_dir / part
                if not part_dir.exists():
                    continue
                
                for prop_file in part_dir.rglob("build.prop"):
                    if self._update_or_append_prop(prop_file, key, value):
                        written += 1
                        logger.debug(f"PropCopyStrategy: Set {key}={value} in {prop_file}")
            
            if written > 0:
                logger.info(f"PropCopyStrategy: Copied {key}={value} to {written} file(s)")
        
        return True
    
    def _read_from_baserom(self, partitions: List[str], key: str) -> Optional[str]:
        """Read property value from baserom partitions."""
        for part in partitions:
            part_dir = self.ctx.baserom.extracted_dir / part
            if not part_dir.exists():
                continue
            
            for prop_file in part_dir.rglob("build.prop"):
                value = self._read_prop_value(prop_file, key)
                if value:
                    return value
        return None
    
    def _read_prop_value(self, file_path: Path, key: str) -> Optional[str]:
        """Read a single property value from file."""
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and line.startswith(f"{key}="):
                        return line.split("=", 1)[1].strip()
        except:
            pass
        return None
    
    def _update_or_append_prop(self, prop_file: Path, key: str, value: str) -> bool:
        """Update existing property or append new one."""
        if not prop_file.exists():
            return False
        
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            # Update existing
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            # Append new
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")
        return True


# Register the new strategy
STRATEGY_REGISTRY["prop_copy"] = PropCopyStrategy
