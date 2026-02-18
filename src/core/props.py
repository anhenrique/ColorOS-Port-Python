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
            return find_prop_in_dir(rom.extracted_dir / part_dir, key, ["system_dlkm", "odm_dlkm"])
        
        # === Base ROM Properties ===
        base_system = baserom.extracted_dir / "system" / "system"
        base_manifest = baserom.extracted_dir / "my_manifest"
        base_product = baserom.extracted_dir / "my_product"
        base_vendor = baserom.extracted_dir / "vendor"
        base_system_ext = baserom.extracted_dir / "system_ext"
        
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
            self.base_market_name = read_prop_from_file(baserom.extracted_dir / "odm" / "build.prop", "ro.vendor.oplus.market.name")
        self.ctx.base_market_name = self.base_market_name
        
        # Market enname
        self.base_market_enname = read_prop_from_file(base_manifest / "build.prop", "ro.vendor.oplus.market.enname")
        if not self.base_market_enname:
            self.base_market_enname = read_prop_from_file(baserom.extracted_dir / "odm" / "build.prop", "ro.vendor.oplus.market.enname")
        self.ctx.base_market_enname = self.base_market_enname
        
        # my_product type
        self.base_my_product_type = read_prop_from_file(base_product / "build.prop", "ro.oplus.image.my_product.type")
        
        # first_api_level
        self.base_product_first_api_level = read_prop_from_file(base_manifest / "build.prop", "ro.product.first_api_level")
        
        # device_family
        self.base_device_family = None
        for prop_file in [baserom.extracted_dir / "odm" / "build.prop", base_product / "build.prop"]:
            self.base_device_family = read_prop_from_file(prop_file, "ro.build.device_family")
            if self.base_device_family:
                break
        
        # vendor brand
        self.base_vendor_brand = read_prop_from_file(base_manifest / "build.prop", "ro.product.vendor.brand")
        
        # Security patch (port rom)
        self.portrom_version_security_patch = read_prop_from_file(portrom.extracted_dir / "my_manifest" / "build.prop", "ro.build.version.security_patch")
        self.ctx.security_patch = self.portrom_version_security_patch
        
        # Region mark
        self.base_regionmark = find_prop_in_dir(baserom.extracted_dir, "ro.vendor.oplus.regionmark")
        if not self.base_regionmark:
            self.base_regionmark = find_prop_in_dir(baserom.extracted_dir, "ro.oplus.image.my_region.type")
            if self.base_regionmark:
                self.base_regionmark = self.base_regionmark.split('_')[0]
        
        # Base area and brand
        self.base_area = find_prop_in_dir(baserom.extracted_dir, "ro.oplus.image.system_ext.area", ["odm"])
        self.base_brand = find_prop_in_dir(baserom.extracted_dir, "ro.oplus.image.system_ext.brand", ["odm"])
        
        # === Port ROM Properties ===
        port_system = portrom.extracted_dir / "system" / "system"
        port_manifest = portrom.extracted_dir / "my_manifest"
        port_product = portrom.extracted_dir / "my_product"
        port_vendor = portrom.extracted_dir / "vendor"
        
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
        self.port_market_name = find_prop_in_dir(portrom.extracted_dir, "ro.vendor.oplus.market.name", ["odm"])
        
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
        self.port_ssi_brand = read_prop_from_file(portrom.extracted_dir / "system_ext" / "etc" / "build.prop", "ro.oplus.image.system_ext.brand")
        
        # first_api_level (port)
        self.port_product_first_api_level = read_prop_from_file(port_manifest / "build.prop", "ro.product.first_api_level")
        
        # device_family (port)
        self.target_device_family = read_prop_from_file(port_product / "build.prop", "ro.build.device_family")
        
        # vendor cpu abilist32
        self.vendor_cpu_abilist32 = read_prop_from_file(port_vendor / "build.prop", "ro.vendor.product.cpu.abilist32")
        
        # Region mark (port)
        self.regionmark = find_prop_in_dir(portrom.extracted_dir, "ro.vendor.oplus.regionmark")
        
        # Area and brand (port)
        self.port_area = find_prop_in_dir(portrom.extracted_dir, "ro.oplus.image.system_ext.area", ["odm"])
        self.port_brand = find_prop_in_dir(portrom.extracted_dir, "ro.oplus.image.system_ext.brand", ["odm"])
        
        # ROM type detection
        self.portIsRealmeUI = (self.port_brand == "realme")
        self.portIsColorOSGlobal = (self.port_area == "gdpr" and self.port_brand != "oneplus")
        self.portIsOOS = (self.port_area == "gdpr" and self.port_brand == "oneplus")
        self.portIsColorOS = not (self.portIsColorOSGlobal or self.portIsOOS or self.portIsRealmeUI)
        
        # LCD Density from base
        self.base_rom_density = find_prop_in_dir(baserom.extracted_dir, "ro.sf.lcd_density", ["odm"])
        if not self.base_rom_density:
            self.base_rom_density = "480"
        
        # AB device check
        is_ab = read_prop_from_file(port_vendor / "build.prop", "ro.build.ab_update")
        self.ctx.is_ab_device = (is_ab == "true")
        
        # ROM version
        self.base_rom_version = read_prop_from_file(baserom.extracted_dir / "my_manifest" / "build.prop", "ro.build.display.ota")
        if self.base_rom_version:
            self.base_rom_version = self.base_rom_version.split('_', 1)[1] if '_' in self.base_rom_version else self.base_rom_version
        
        self.port_rom_version = read_prop_from_file(portrom.extracted_dir / "my_manifest" / "build.prop", "ro.build.display.ota")
        if self.port_rom_version:
            self.port_rom_version = self.port_rom_version.split('_', 1)[1] if '_' in self.port_rom_version else self.port_rom_version
        
        self.ctx.target_rom_version = self.port_rom_version or "1.0"
        
        # Log summary
        logger.info(f"Base Android: {self.base_android_version}, SDK: {self.base_android_sdk}")
        logger.info(f"Port Android: {self.port_android_version}, SDK: {self.port_android_sdk}")
        logger.info(f"Device Code: Base={self.base_device_code}, Port={self.port_device_code}")
        logger.info(f"AB Device: {self.ctx.is_ab_device}")
        
    def _modify_build_props(self):
        """Main build.prop modification - port.sh lines 1340-1600"""
        self._modify_all_build_props()
        self._modify_my_product_props()
        self._modify_system_ext_props()
        logger.info("Build.prop modifications complete.")

    def _modify_all_build_props(self):
        """Modify all build.prop files - port.sh lines 1345-1376"""
        portrom = self.ctx.portrom
        
        # Find all build.prop files in portrom images
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
                (self.port_device_code, self.base_device_code),
                (self.port_product_model, self.base_product_model),
                (self.port_product_name, self.base_product_name),
                (self.port_my_product_type, self.base_my_product_type),
                (self.port_product_device, self.base_product_device),
            ]
            
            for old_val, new_val in replacements:
                if old_val and new_val and old_val != new_val:
                    if old_val in content:
                        content = content.replace(old_val, new_val)
                        modified = True
            
            # Display ID
            if self.target_display_id:
                content = re.sub(r'ro\.build\.display\.id=.*', f'ro.build.display.id={self.target_display_id}', content)
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
        if self.base_market_name:
            self._add_or_replace_prop(bruce_prop, "ro.vendor.oplus.market.name", self.base_market_name)
        if self.base_market_enname:
            self._add_or_replace_prop(bruce_prop, "ro.vendor.oplus.market.enname", self.base_market_enname)
        
        # Ported by watermark
        oplusrom_prop = my_product_prop if my_product_prop.exists() else bruce_prop
        if self._read_prop_value(oplusrom_prop, "ro.build.version.oplusrom.display"):
            self._add_or_replace_prop(oplusrom_prop, "ro.build.version.oplusrom.display", 
                                      self._read_prop_value(oplusrom_prop, "ro.build.version.oplusrom.display") + " | Ported By BT")
        
        # RealmeUI version
        if getattr(self, 'portIsRealmeUI', False):
            rui_version_map = {"16": "7.0", "15": "6.0", "14": "5.0"}
            rui_version = rui_version_map.get(self.port_android_version, "5.0")
            self._add_prop(bruce_prop, f"ro.build.version.realmeui={rui_version}")
        
        # Magic model props
        self._add_prop(bruce_prop, f"persist.oplus.prophook.com.oplus.ai.magicstudio=MODEL:{self.base_device_code},BRAND:{self.base_product_model}")
        self._add_prop(bruce_prop, f"persist.oplus.prophook.com.oplus.aiunit=MODEL:{self.base_device_code},BRAND:{self.base_product_model}")
        
        # LCD Density from base
        if self.base_rom_density:
            self._add_or_replace_prop(my_product_prop, "ro.sf.lcd_density", self.base_rom_density)

    def _modify_system_ext_props(self):
        """Modify system_ext build.prop"""
        target_system_ext = self.target_dir / "system_ext"
        if not target_system_ext.exists():
            return
        
        system_ext_prop = target_system_ext / "etc" / "build.prop"
        if not system_ext_prop.exists():
            return
        
        # Brand replacement
        if (getattr(self, 'portIsColorOSGlobal', False) == False and 
            self.port_android_version and int(self.port_android_version) < 16):
            if self.base_vendor_brand and self.port_vendor_brand:
                base_brand_lower = self.base_vendor_brand.lower()
                port_brand_lower = self.port_vendor_brand.lower()
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
