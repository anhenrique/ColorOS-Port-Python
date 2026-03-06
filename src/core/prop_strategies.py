"""
Property modification strategies - Function-based design.

High-level strategies grouped by function:
- string_replace: Global string replacements (device code, model, etc.)
- prop_set: Set property values directly
- prop_copy: Copy properties from baserom to target
- magic_model: Set AI magic model properties with template
- watermark: Add version watermark
- fingerprint: Regenerate build fingerprint
"""

import re
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        pass
    
    def check_condition(self) -> bool:
        """Check if strategy's condition is satisfied."""
        condition = self.config.get("condition")
        if not condition:
            return True
        
        # Simple condition evaluation
        for key, expected in condition.items():
            actual = self._get_context_value(key)
            if actual is None:
                return False
            
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
        """Get value from context using key mapping."""
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
        return getattr(self.ctx, key, None)


class StringReplaceStrategy(PropStrategy):
    """
    Global string replacement across all build.prop files.
    Replaces port values with base values (e.g., device code, model).
    """
    
    def apply(self, target_dir: Path) -> bool:
        mappings = self.config["config"].get("mappings", [])
        
        # Build replacement pairs
        replacements = []
        for mapping in mappings:
            old_val = self._get_context_value(mapping["from"])
            new_val = self._get_context_value(mapping["to"])
            if old_val and new_val and old_val != new_val:
                replacements.append((old_val, new_val))
        
        if not replacements:
            return True
        
        for prop_file in target_dir.rglob("build.prop"):
            if "system_dlkm" in str(prop_file) or "odm_dlkm" in str(prop_file):
                continue
            
            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            original = content
            
            for old_val, new_val in replacements:
                content = content.replace(old_val, new_val)
            
            if content != original:
                prop_file.write_text(content, encoding="utf-8")
        
        return True


class PropSetStrategy(PropStrategy):
    """
    Set property values directly.
    Supports static values, context sources, templates, and partition-specific targets.
    """
    
    def apply(self, target_dir: Path) -> bool:
        properties = self.config["config"].get("properties", [])
        
        for prop in properties:
            key = prop["key"]
            
            # Get value: static value, from context, or from template
            value = self._resolve_value(prop)
            if not value:
                continue
            
            # Determine target partition
            target_partition = prop.get("target_partition")
            
            if target_partition:
                # Specific partition
                target_file = target_dir / target_partition / "build.prop"
                if target_file.exists():
                    self._update_or_append(target_file, key, value)
            else:
                # Default: my_product/etc/bruce/build.prop
                bruce_prop = target_dir / "my_product" / "etc" / "bruce" / "build.prop"
                if bruce_prop.exists() or prop.get("create_if_missing", True):
                    self._update_or_append(bruce_prop, key, value)
        
        return True
    
    def _resolve_value(self, prop: Dict[str, Any]) -> Optional[str]:
        """Resolve property value from various sources."""
        # Direct static value
        if "value" in prop:
            return prop["value"]
        
        # Template with variable substitution
        if "template" in prop:
            template = prop["template"]
            # Collect template variables from context
            vars = {}
            if "{device_code}" in template:
                vars["device_code"] = self.ctx.baserom.device_code or ""
            if "{product_model}" in template:
                vars["product_model"] = self.ctx.baserom.product_model or ""
            if "{vendor_brand}" in template:
                vars["vendor_brand"] = self.ctx.baserom.vendor_brand or ""
            return template.format(**vars)
        
        # Context source
        if "source" in prop:
            return self._get_context_value(prop["source"])
        
        return None
    
    def _update_or_append(self, prop_file: Path, key: str, value: str):
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class PropCopyStrategy(PropStrategy):
    """
    Copy properties from baserom to target partitions.
    Used for critical properties that must match baserom (e.g., first_api_level).
    """
    
    def apply(self, target_dir: Path) -> bool:
        properties = self.config["config"].get("properties", [])
        
        for prop in properties:
            key = prop["key"]
            to_partition = prop.get("to_partition", "my_manifest")
            fallback_key = prop.get("fallback_key")
            
            logger.debug(f"PropCopy: Processing {key}")
            
            # Read from baserom's already parsed props
            value = self._get_baserom_prop(key)
            
            # If not found, try fallback key
            if not value and fallback_key:
                value = self._get_baserom_prop(fallback_key)
                if value:
                    logger.debug(f"PropCopy: Using fallback {fallback_key}={value} for {key}")
            
            if not value:
                logger.warning(f"PropCopy: {key} not found in baserom props")
                continue
            
            logger.debug(f"PropCopy: Found {key}={value} in baserom")
            
            # Write to target partition
            target_partition_dir = target_dir / to_partition
            target_file = self._find_build_prop(target_partition_dir)
            
            if not target_file.exists():
                # Create target file if needed
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text("", encoding="utf-8")
            
            self._update_or_append(target_file, key, value)
            logger.info(f"PropCopy: Copied {key}={value} to {target_file}")
        
        return True
    
    def _get_baserom_prop(self, key: str) -> Optional[str]:
        """Get property value from baserom's parsed props."""
        # Try direct access from RomPackage.props
        if hasattr(self.ctx.baserom, 'props') and key in self.ctx.baserom.props:
            return self.ctx.baserom.props[key]
        
        # Fallback: read from extracted files
        for part in ["my_manifest", "product", "system", "vendor"]:
            part_dir = self.ctx.baserom.extracted_dir / part
            if not part_dir.exists():
                continue
            for prop_file in part_dir.rglob("build.prop"):
                value = self._read_prop_value(prop_file, key)
                if value:
                    return value
        return None
    
    def _find_build_prop(self, partition_dir: Path) -> Path:
        """Find build.prop in partition directory."""
        direct = partition_dir / "build.prop"
        if direct.exists():
            return direct
        nested = partition_dir / "etc" / "build.prop"
        return nested
    
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
    
    def _update_or_append(self, prop_file: Path, key: str, value: str):
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class WatermarkStrategy(PropStrategy):
    """Add watermark to ROM version display."""
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        target_key = cfg["target_key"]
        template = cfg["template"]
        author = cfg.get("author", "BT")
        skip_if_contains = cfg.get("skip_if_contains", "")
        
        my_product = target_dir / "my_product"
        if not my_product.exists():
            return True
        
        prop_main = my_product / "build.prop"
        prop_bruce = my_product / "etc" / "bruce" / "build.prop"
        target_file = prop_main if prop_main.exists() else prop_bruce
        
        if not target_file.exists():
            return True
        
        current_value = self._read_prop_value(target_file, target_key)
        if not current_value or skip_if_contains in current_value:
            return True
        
        new_value = template.format(value=current_value, author=author)
        self._update_or_append(target_file, target_key, new_value)
        
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
    
    def _update_or_append(self, prop_file: Path, key: str, value: str):
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding="utf-8")


class FingerprintStrategy(PropStrategy):
    """Regenerate build fingerprint and description."""
    
    def apply(self, target_dir: Path) -> bool:
        cfg = self.config["config"]
        priority_partitions = cfg.get("priority_partitions", 
            ["my_manifest", "my_product", "odm", "vendor", "product", "system_ext", "system"])
        
        # Read components
        brand = self._get_prop(target_dir, priority_partitions, "ro.product.brand", "OnePlus")
        name = self._get_prop(target_dir, priority_partitions, "ro.product.name", "")
        device = self._get_prop(target_dir, priority_partitions, "ro.product.device", "oplus")
        version = self._get_prop(target_dir, priority_partitions, "ro.build.version.release", "")
        build_id = self._get_prop(target_dir, priority_partitions, "ro.build.id", "")
        incremental = self._get_prop(target_dir, priority_partitions, "ro.build.version.incremental", "")
        build_type = self._get_prop(target_dir, priority_partitions, "ro.build.type", "user")
        tags = self._get_prop(target_dir, priority_partitions, "ro.build.tags", "release-keys")
        
        fingerprint = f"{brand}/{name}/{device}:{version}/{build_id}/{incremental}:{build_type}/{tags}"
        description = f"{name}-{build_type} {version} {build_id} {incremental} {tags}"
        
        logger.info(f"Fingerprint: {fingerprint}")
        
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
        
        for prop_file in target_dir.rglob("build.prop"):
            self._apply_replacements(prop_file, replacements)
        
        return True
    
    def _get_prop(self, target_dir: Path, partitions: List[str], key: str, default: str) -> str:
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
        changed = False
        
        for line in lines:
            original = line
            stripped = line.strip()
            replaced = False
            
            for prefix, new_val in replacements.items():
                if stripped.startswith(prefix):
                    if original.strip() != new_val:
                        new_lines.append(new_val + "\n")
                        changed = True
                    else:
                        new_lines.append(original)
                    replaced = True
                    break
            
            if not replaced:
                new_lines.append(original)
        
        if changed:
            with open(prop_file, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)


# Strategy registry
STRATEGY_REGISTRY = {
    "string_replace": StringReplaceStrategy,
    "prop_set": PropSetStrategy,
    "prop_copy": PropCopyStrategy,
    "watermark": WatermarkStrategy,
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
