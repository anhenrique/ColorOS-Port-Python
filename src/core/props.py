import logging
import re
from pathlib import Path
from typing import Callable, Union, Match
from src.core.context import Context

logger = logging.getLogger(__name__)

def read_prop_from_file(file_path: Path, key: str) -> str | None:
    """Helper to read a prop from a file - port.sh grep logic"""
    if not file_path or not file_path.exists():
        return None
    try:
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line.startswith(key + '='):
                    return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return None

def find_prop_in_dir(search_dir: Path, key: str, exclude_dirs: list[str] = None) -> str | None:
    """Find property in build.prop files within a directory - port.sh find logic"""
    if not search_dir or not search_dir.exists():
        return None
    
    exclude_dirs = exclude_dirs or []
    
    for f in search_dir.rglob("build.prop"):
        # Skip excluded directories
        skip = False
        for ex in exclude_dirs:
            if ex in str(f):
                skip = True
                break
        if skip:
            continue
        
        val = read_prop_from_file(f, key)
        if val:
            return val
    return None


class PropertyModifier:
    def __init__(self, context: Context):
        self.ctx = context
        self.target_dir = self.ctx.target_dir

    def run(self):
        logger.info("Starting Property Modification...")
        
        # 1. Fetch Basic Info (populates context with ROM properties)
        self._fetch_rom_info()
        
        # 2. Modify build.prop files
        self._modify_build_props()
        
    def _fetch_rom_info(self):
        """Fetch all ROM properties - port.sh lines 407-577 logic"""
        
        baserom = self.ctx.baserom
        portrom = self.ctx.portrom
        
        # Helper to find prop in images directory
        def find_in_images(rom, part_dir, key):
            return find_prop_in_dir(rom.images_dir / part_dir, key, ["system_dlkm", "odm_dlkm"])
        
        # === Base ROM Properties ===
        base_system = baserom.images_dir / "system" / "system"
        base_manifest = baserom.images_dir / "my_manifest"
        base_product = baserom.images_dir / "my_product"
        base_vendor = baserom.images_dir / "vendor"
        base_system_ext = baserom.images_dir / "system_ext"
        
        # Android version
        self.base_android_version = read_prop_from_file(base_system / "build.prop", "ro.build.version.release")
        self.ctx.base_android_version = self.base_android_version
        
        # SDK version
        self.base_android_sdk = read_prop_from_file(base_system / "build.prop", "ro.system.build.version.sdk")
        self.ctx.base_android_sdk = self.base_android_sdk
        
        # Device code (oplus version)
        self.base_device_code = read_prop_from_file(base_manifest / "build.prop", "ro.oplus.version.my_manifest")
        if self.base_device_code:
            self.base_device_code = self.base_device_code.split('_')[0]
        self.ctx.base_device_code = self.base_device_code
        
        # Product device
        self.base_product_device = read_prop_from_file(base_manifest / "build.prop", "ro.product.device")
        self.ctx.base_product_device = self.base_product_device
        
        # Product name
        self.base_product_name = read_prop_from_file(base_manifest / "build.prop", "ro.product.name")
        self.ctx.base_product_name = self.base_product_name
        
        # Product model
        self.base_product_model = read_prop_from_file(base_manifest / "build.prop", "ro.product.model")
        self.ctx.base_product_model = self.base_product_model
        
        # Market name
        self.base_market_name = read_prop_from_file(base_manifest / "build.prop", "ro.vendor.oplus.market.name")
        if not self.base_market_name:
            self.base_market_name = read_prop_from_file(baserom.images_dir / "odm" / "build.prop", "ro.vendor.oplus.market.name")
        self.ctx.base_market_name = self.base_market_name
        
        # Market enname
        self.base_market_enname = read_prop_from_file(base_manifest / "build.prop", "ro.vendor.oplus.market.enname")
        if not self.base_market_enname:
            self.base_market_enname = read_prop_from_file(baserom.images_dir / "odm" / "build.prop", "ro.vendor.oplus.market.enname")
        self.ctx.base_market_enname = self.base_market_enname
        
        # my_product type
        self.base_my_product_type = read_prop_from_file(base_product / "build.prop", "ro.oplus.image.my_product.type")
        
        # first_api_level
        self.base_product_first_api_level = read_prop_from_file(base_manifest / "build.prop", "ro.product.first_api_level")
        
        # device_family
        self.base_device_family = None
        for prop_file in [baserom.images_dir / "odm" / "build.prop", base_product / "build.prop"]:
            self.base_device_family = read_prop_from_file(prop_file, "ro.build.device_family")
            if self.base_device_family:
                break
        
        # vendor brand
        self.base_vendor_brand = read_prop_from_file(base_manifest / "build.prop", "ro.product.vendor.brand")
        
        # Security patch (port rom)
        self.portrom_version_security_patch = read_prop_from_file(portrom.images_dir / "my_manifest" / "build.prop", "ro.build.version.security_patch")
        self.ctx.security_patch = self.portrom_version_security_patch
        
        # Region mark
        self.base_regionmark = find_prop_in_dir(baserom.images_dir, "ro.vendor.oplus.regionmark")
        if not self.base_regionmark:
            self.base_regionmark = find_prop_in_dir(baserom.images_dir, "ro.oplus.image.my_region.type")
            if self.base_regionmark:
                self.base_regionmark = self.base_regionmark.split('_')[0]
        
        # Base area and brand
        self.base_area = find_prop_in_dir(baserom.images_dir, "ro.oplus.image.system_ext.area", ["odm"])
        self.base_brand = find_prop_in_dir(baserom.images_dir, "ro.oplus.image.system_ext.brand", ["odm"])
        
        # === Port ROM Properties ===
        port_system = portrom.images_dir / "system" / "system"
        port_manifest = portrom.images_dir / "my_manifest"
        port_product = portrom.images_dir / "my_product"
        port_vendor = portrom.images_dir / "vendor"
        
        self.port_android_version = read_prop_from_file(port_system / "build.prop", "ro.build.version.release")
        self.ctx.port_android_version = self.port_android_version
        
        self.port_android_sdk = read_prop_from_file(port_system / "build.prop", "ro.system.build.version.sdk")
        self.ctx.port_android_sdk = self.port_android_sdk
        
        self.port_device_code = read_prop_from_file(port_manifest / "build.prop", "ro.oplus.version.my_manifest")
        if self.port_device_code:
            self.port_device_code = self.port_device_code.split('_')[0]
        
        self.port_product_device = read_prop_from_file(port_manifest / "build.prop", "ro.product.device")
        
        self.port_product_name = read_prop_from_file(port_manifest / "build.prop", "ro.product.name")
        
        self.port_product_model = read_prop_from_file(port_manifest / "build.prop", "ro.product.model")
        
        # Market name (port)
        self.port_market_name = find_prop_in_dir(portrom.images_dir, "ro.vendor.oplus.market.name", ["odm"])
        
        self.port_my_product_type = read_prop_from_file(port_product / "build.prop", "ro.oplus.image.my_product.type")
        
        # target_display_id (with replacement)
        target_display_id_orig = read_prop_from_file(port_manifest / "build.prop", "ro.build.display.id")
        if target_display_id_orig and self.port_device_code and self.base_device_code:
            self.target_display_id = target_display_id_orig.replace(self.port_device_code, self.base_device_code)
        else:
            self.target_display_id = target_display_id_orig
        
        target_display_id_show = read_prop_from_file(port_manifest / "build.prop", "ro.build.display.id.show")
        if target_display_id_show and self.port_device_code and self.base_device_code:
            self.target_display_id_show = target_display_id_show.replace(self.port_device_code, self.base_device_code)
        else:
            self.target_display_id_show = target_display_id_show
        
        # vendor brand (port)
        self.port_vendor_brand = read_prop_from_file(port_manifest / "build.prop", "ro.product.vendor.brand")
        
        # ssi brand
        self.port_ssi_brand = read_prop_from_file(portrom.images_dir / "system_ext" / "etc" / "build.prop", "ro.oplus.image.system_ext.brand")
        
        # first_api_level (port)
        self.port_product_first_api_level = read_prop_from_file(port_manifest / "build.prop", "ro.product.first_api_level")
        
        # device_family (port)
        self.target_device_family = read_prop_from_file(port_product / "build.prop", "ro.build.device_family")
        
        # vendor cpu abilist32
        self.vendor_cpu_abilist32 = read_prop_from_file(port_vendor / "build.prop", "ro.vendor.product.cpu.abilist32")
        
        # Region mark (port)
        self.regionmark = find_prop_in_dir(portrom.images_dir, "ro.vendor.oplus.regionmark")
        
        # Area and brand (port)
        self.port_area = find_prop_in_dir(portrom.images_dir, "ro.oplus.image.system_ext.area", ["odm"])
        self.port_brand = find_prop_in_dir(portrom.images_dir, "ro.oplus.image.system_ext.brand", ["odm"])
        
        # AB device check
        is_ab = read_prop_from_file(port_vendor / "build.prop", "ro.build.ab_update")
        self.ctx.is_ab_device = (is_ab == "true")
        
        # ROM version
        self.base_rom_version = read_prop_from_file(baserom.images_dir / "my_manifest" / "build.prop", "ro.build.display.ota")
        if self.base_rom_version:
            self.base_rom_version = self.base_rom_version.split('_', 1)[1] if '_' in self.base_rom_version else self.base_rom_version
        
        self.port_rom_version = read_prop_from_file(portrom.images_dir / "my_manifest" / "build.prop", "ro.build.display.ota")
        if self.port_rom_version:
            self.port_rom_version = self.port_rom_version.split('_', 1)[1] if '_' in self.port_rom_version else self.port_rom_version
        
        self.ctx.target_rom_version = self.port_rom_version or "1.0"
        
        # Log summary
        logger.info(f"Base Android: {self.base_android_version}, SDK: {self.base_android_sdk}")
        logger.info(f"Port Android: {self.port_android_version}, SDK: {self.port_android_sdk}")
        logger.info(f"Device Code: Base={self.base_device_code}, Port={self.port_device_code}")
        logger.info(f"AB Device: {self.ctx.is_ab_device}")
        
    def _modify_build_props(self):
        target_manifest_prop = self.target_dir / "my_manifest" / "build.prop"
        
        if not target_manifest_prop.exists():
            logger.warning(f"{target_manifest_prop} not found, skipping specific modifications.")
            return

        # 1. Update ro.build.display.id
        def replace_display_id(match: Match[str]) -> str:
            original = match.group(0)
            if self.port_device_code and self.base_device_code:
                return original.replace(self.port_device_code, self.base_device_code)
            return original

        self._sed_file(target_manifest_prop, 
                       f"ro.build.display.id=.*", 
                       replace_display_id)

        # 2. Update ro.product.first_api_level
        base_manifest_prop = self.ctx.baserom.extracted_dir / "my_manifest" / "build.prop"
        base_first_api = self._read_prop_value(base_manifest_prop, "ro.product.first_api_level")
        
        if base_first_api:
             self._sed_file(target_manifest_prop, 
                            "ro.product.first_api_level=.*", 
                            f"ro.product.first_api_level={base_first_api}")

        # 3. Update Market Name and Enname
        base_market_name = self._read_prop_value(base_manifest_prop, "ro.vendor.oplus.market.name")
        base_market_enname = self._read_prop_value(base_manifest_prop, "ro.vendor.oplus.market.enname")
        
        if base_market_name:
             self._sed_file(target_manifest_prop, "ro.vendor.oplus.market.name=.*", f"ro.vendor.oplus.market.name={base_market_name}")
        
        if base_market_enname:
             self._sed_file(target_manifest_prop, "ro.vendor.oplus.market.enname=.*", f"ro.vendor.oplus.market.enname={base_market_enname}")

        # 4. Remove unwanted properties
        self._sed_file(target_manifest_prop, "ro.build.version.release=.*", "") 
        self._sed_file(target_manifest_prop, "ro.oplus.watermark.betaversiononly.enable=.*", "")

        # 5. Fix for Android 14 Base (if applicable)
        if self.base_android_version and self.base_android_version <= "14":
             keys = ["ro.product.name", "ro.product.model", "ro.product.manufacturer", "ro.product.device", "ro.product.brand", "ro.oplus.image.my_product.type"]
             for key in keys:
                 val = self._read_prop_value(base_manifest_prop, key)
                 if val:
                     if key == "ro.product.vendor.brand":
                         val = "OPPO" # Special case
                     
                     self._sed_file(target_manifest_prop, f"^{key}=.*", f"{key}={val}")

        logger.info("Build.prop modifications complete.")

    def _read_prop_value(self, file_path, key):
        if not file_path.exists():
            return None
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments, match ^key= format
                if line and not line.startswith('#') and line.startswith(key + '='):
                    return line.split('=', 1)[1].strip()
        return None

    def _sed_file(self, file_path: Path, pattern: str, replacement: Union[str, Callable[[Match[str]], str]]):
        if not file_path.exists():
            return
            
        with open(file_path, 'r', errors='ignore') as f:
            lines = f.readlines()
            
        with open(file_path, 'w') as f:
            for line in lines:
                if re.search(pattern, line):
                    if replacement == "":
                        continue
                    elif callable(replacement):
                         new_line = re.sub(pattern, replacement, line)
                         f.write(new_line)
                    elif isinstance(replacement, str):
                         if not replacement.endswith('\n'):
                             replacement += '\n'
                         f.write(replacement)
                else:
                    f.write(line)
