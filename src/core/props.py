import logging
import re
from pathlib import Path
from typing import Callable, Union, Match
from src.core.context import Context

logger = logging.getLogger(__name__)

class PropertyModifier:
    def __init__(self, context: Context):
        self.ctx = context
        self.target_dir = self.ctx.target_dir

    def run(self):
        logger.info("Starting Property Modification...")
        
        # 1. Fetch Basic Info
        self._fetch_rom_info()
        
        # 2. Modify build.prop files
        self._modify_build_props()
        
    def _fetch_rom_info(self):
        # Helper to read a prop from a file
        def read_prop(file_path, key):
            if not file_path.exists():
                return None
            with open(file_path, 'r', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments, match ^key= format
                    if line and not line.startswith('#') and line.startswith(key + '='):
                        return line.split('=', 1)[1].strip()
            return None

        # Base ROM Info - read from extracted partitions
        base_system_prop = self.ctx.baserom.extracted_dir / "system/build.prop"
        base_manifest_prop = self.ctx.baserom.extracted_dir / "my_manifest/build.prop"
        
        self.base_android_version = read_prop(base_system_prop, "ro.build.version.release")
        self.base_android_sdk = read_prop(base_system_prop, "ro.system.build.version.sdk")
        self.base_device_code = read_prop(base_manifest_prop, "ro.oplus.version.my_manifest")
        
        if self.base_device_code:
             self.base_device_code = self.base_device_code.split('_')[0]

        # Port ROM Info
        port_system_prop = self.ctx.portrom.extracted_dir / "system/build.prop"
        port_manifest_prop = self.ctx.portrom.extracted_dir / "my_manifest/build.prop"
        
        self.port_android_version = read_prop(port_system_prop, "ro.build.version.release")
        self.port_android_sdk = read_prop(port_system_prop, "ro.system.build.version.sdk")
        self.port_device_code = read_prop(port_manifest_prop, "ro.oplus.version.my_manifest")
        
        if self.port_device_code:
             self.port_device_code = self.port_device_code.split('_')[0]

        logger.info(f"Base Android: {self.base_android_version}, SDK: {self.base_android_sdk}")
        logger.info(f"Port Android: {self.port_android_version}, SDK: {self.port_android_sdk}")
        
    def _modify_build_props(self):
        target_manifest_prop = self.target_dir / "my_manifest/build.prop"
        
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
        base_manifest_prop = self.ctx.baserom.extracted_dir / "my_manifest/build.prop"
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
