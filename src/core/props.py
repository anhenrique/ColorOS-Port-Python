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
        
        # 1. Fetch ROM Info (populates context with properties)
        self.ctx.fetch_rom_info()
        
        # 2. Modify build.prop files
        self._modify_build_props()
        
    def _modify_build_props(self):
        """Main build.prop modification - port.sh lines 1340-1600"""
        self._modify_all_build_props()
        self._modify_my_product_props()
        self._modify_system_ext_props()
        logger.info("Build.prop modifications complete.")

    def _modify_all_build_props(self):
        """Modify all build.prop files - port.sh lines 1345-1376"""
        portrom = self.ctx.portrom
        
        # Find all build.prop files in portrom extracted_dir
        for build_prop in portrom.extracted_dir.rglob("build.prop"):
            if "system_dlkm" in str(build_prop) or "odm_dlkm" in str(build_prop):
                continue
            
            content = build_prop.read_text(encoding='utf-8', errors='ignore')
            modified = False
            
            # Timezone
            if "persist.sys.timezone=" in content:
                content = re.sub(r'persist\.sys\.timezone=.*', 'persist.sys.timezone=Asia/Shanghai', content)
                modified = True
            
            # Global replacements (port -> base)
            replacements = [
                (self.ctx.port_device_code, self.ctx.base_device_code),
                (self.ctx.port_product_model, self.ctx.base_product_model),
                (self.ctx.port_product_name, self.ctx.base_product_name),
                (self.ctx.port_my_product_type, self.ctx.base_my_product_type),
                (self.ctx.port_product_device, self.ctx.base_product_device),
            ]
            
            for old_val, new_val in replacements:
                if old_val and new_val and old_val != new_val:
                    if old_val in content:
                        content = content.replace(old_val, new_val)
                        modified = True
            
            # Display ID
            if self.ctx.target_display_id:
                content = re.sub(r'ro\.build\.display\.id=.*', f'ro.build.display.id={self.ctx.target_display_id}', content)
                modified = True
            
            # Region lock
            content = re.sub(r'ro\.oplus\.radio\.global_regionlock\.enabled=.*', 'ro.oplus.radio.global_regionlock.enabled=false', content)
            content = re.sub(r'persist\.sys\.radio\.global_regionlock\.allcheck=.*', 'persist.sys.radio.global_regionlock.allcheck=false', content)
            content = re.sub(r'ro\.oplus\.radio\.checkservice=.*', 'ro.oplus.radio.checkservice=false', content)
            modified = True
            
            if modified:
                build_prop.write_text(content, encoding='utf-8')

    def _modify_my_product_props(self):
        """Modify my_product build.prop - port.sh lines 1378-1522"""
        target_my_product = self.target_dir / "my_product"
        if not target_my_product.exists():
            return
        
        bruce_prop = target_my_product / "etc" / "bruce" / "build.prop"
        my_product_prop = target_my_product / "build.prop"
        
        # Market name/enname
        if self.ctx.base_market_name:
            self._add_or_replace_prop(bruce_prop, "ro.vendor.oplus.market.name", self.ctx.base_market_name)
        if self.ctx.base_market_enname:
            self._add_or_replace_prop(bruce_prop, "ro.vendor.oplus.market.enname", self.ctx.base_market_enname)
        
        # Ported by watermark
        oplusrom_prop = my_product_prop if my_product_prop.exists() else bruce_prop
        if self._read_prop_value(oplusrom_prop, "ro.build.version.oplusrom.display"):
            self._add_or_replace_prop(oplusrom_prop, "ro.build.version.oplusrom.display", 
                                      self._read_prop_value(oplusrom_prop, "ro.build.version.oplusrom.display") + " | Ported By BT")
        
        # RealmeUI version
        if self.ctx.portIsRealmeUI:
            rui_version_map = {"16": "7.0", "15": "6.0", "14": "5.0"}
            rui_version = rui_version_map.get(self.ctx.port_android_version, "5.0")
            self._add_prop(bruce_prop, f"ro.build.version.realmeui={rui_version}")
        
        # Magic model props
        self._add_prop(bruce_prop, f"persist.oplus.prophook.com.oplus.ai.magicstudio=MODEL:{self.ctx.base_device_code},BRAND:{self.ctx.base_product_model}")
        self._add_prop(bruce_prop, f"persist.oplus.prophook.com.oplus.aiunit=MODEL:{self.ctx.base_device_code},BRAND:{self.ctx.base_product_model}")
        
        # LCD Density from base
        if self.ctx.base_rom_density:
            self._add_or_replace_prop(my_product_prop, "ro.sf.lcd_density", self.ctx.base_rom_density)

    def _modify_system_ext_props(self):
        """Modify system_ext build.prop"""
        target_system_ext = self.target_dir / "system_ext"
        if not target_system_ext.exists():
            return
        
        system_ext_prop = target_system_ext / "etc" / "build.prop"
        if not system_ext_prop.exists():
            return
        
        # Brand replacement
        if (self.ctx.portIsColorOSGlobal == False and 
            self.ctx.port_android_version and int(self.ctx.port_android_version) < 16):
            if self.ctx.base_vendor_brand and self.ctx.port_vendor_brand:
                base_brand_lower = self.ctx.base_vendor_brand.lower()
                port_brand_lower = self.ctx.port_vendor_brand.lower()
                if base_brand_lower != port_brand_lower:
                    content = system_ext_prop.read_text(encoding='utf-8', errors='ignore')
                    content = re.sub(r'ro\.oplus\.image\.system_ext\.brand=.*', 
                                    f'ro.oplus.image.system_ext.brand={base_brand_lower}', content)
                    system_ext_prop.write_text(content, encoding='utf-8')

    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        """Add or replace a property in build.prop"""
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding='utf-8')
        
        content = prop_file.read_text(encoding='utf-8', errors='ignore')
        
        # Check if exists
        if re.search(rf'^{re.escape(key)}=', content, re.MULTILINE):
            content = re.sub(rf'^{re.escape(key)}=.*', f'{key}={value}', content, flags=re.MULTILINE)
        else:
            content += f"\n{key}={value}\n"
        
        prop_file.write_text(content, encoding='utf-8')

    def _add_prop(self, prop_file: Path, prop_line: str):
        """Add a property line to build.prop"""
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding='utf-8')
        
        content = prop_file.read_text(encoding='utf-8', errors='ignore')
        content += f"\n{prop_line}\n"
        prop_file.write_text(content, encoding='utf-8')

    def _read_prop_value(self, file_path, key):
        if not file_path.exists():
            return None
        with open(file_path, 'r', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and line.startswith(key + '='):
                    return line.split('=', 1)[1].strip()
        return None
