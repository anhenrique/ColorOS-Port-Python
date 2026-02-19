import shutil
import logging
import concurrent.futures
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.tools import ToolManager
from src.utils.shell import Shell

logger = logging.getLogger(__name__)


class Context:
    def __init__(self, config: Config, baserom: RomPackage, portrom: RomPackage, work_dir: str | Path, device_code: str | None = None):
        self.config = config
        self.baserom = baserom
        self.portrom = portrom
        
        # Compatibility aliases for modifier.py
        self.stock = baserom
        self.port = portrom
        
        self.work_dir = Path(work_dir).resolve()
        self.device_code = device_code
        self.stock_rom_code = device_code
        
        # ROM properties (will be populated by fetch_rom_info)
        self.base_android_version = None
        self.base_android_sdk = None
        self.base_device_code = None
        self.base_product_device = None
        self.base_product_name = None
        self.base_product_model = None
        self.base_market_name = None
        self.base_market_enname = None
        self.base_regionmark = None
        self.base_chipset_family = "unknown"
        self.base_rom_density = "480"
        self.base_vendor_brand = None
        self.base_my_product_type = None
        
        self.port_android_version = None
        self.port_android_sdk = None
        self.port_chipset_family = "unknown"
        self.port_device_code = None
        self.port_product_device = None
        self.port_product_name = None
        self.port_product_model = None
        self.port_my_product_type = None
        self.port_market_name = None
        self.port_vendor_brand = None
        self.port_area = None
        self.port_brand = None
        self.target_display_id = None
        
        self.portIsRealmeUI = False
        self.portIsColorOSGlobal = False
        self.portIsOOS = False
        self.portIsColorOS = True
        
        self.security_patch = None
        self.is_ab_device = False
        self.target_rom_version = "1.0"
        
        self.logger = logger
        
        self.build_dir = self.work_dir
        self.target_dir = self.build_dir / "target"
        self.repack_dir = self.build_dir / "repack"
        self.target_config_dir = self.target_dir / "config"
        self.repack_images_dir = self.work_dir / "repack_images"

        # Initialize tools
        self.bin_root = Path("bin").resolve()
        self.tools = ToolManager(self.bin_root)
        
        self._init_workspace()

    def fetch_rom_info(self):
        """Fetch all ROM properties from baserom and portrom using get_prop (cached)"""
        self.logger.info("Fetching ROM properties...")
        
        baserom = self.baserom
        portrom = self.portrom
        
        # === Base ROM Properties ===
        self.base_android_version = baserom.get_prop("ro.build.version.release")
        self.base_android_sdk = baserom.get_prop("ro.system.build.version.sdk")
        
        self.base_product_device = baserom.get_prop("ro.product.device")
        self.base_product_name = baserom.get_prop("ro.product.name")
        self.base_product_model = baserom.get_prop("ro.product.model")
        
        base_device_code = baserom.get_prop("ro.oplus.version.my_manifest")
        if base_device_code:
            self.base_device_code = base_device_code.split('_')[0].upper()
        else:
            self.base_device_code = self.base_product_device.upper() if self.base_product_device else "UNKNOWN"
        
        self.base_vendor_brand = baserom.get_prop("ro.product.vendor.brand")
        
        # Extract Chipset Family (e.g., OPSM8250)
        self.base_chipset_family = baserom.get_prop("ro.build.device_family")
        if not self.base_chipset_family:
            self.base_chipset_family = "unknown"
        
        self.base_market_name = baserom.get_prop("ro.vendor.oplus.market.name")
        if not self.base_market_name:
            self.base_market_name = baserom.get_prop("ro.oplus.market.name")
        
        self.base_market_enname = baserom.get_prop("ro.vendor.oplus.market.enname")
        if not self.base_market_enname:
            self.base_market_enname = baserom.get_prop("ro.oplus.market.enname")
        
        self.base_regionmark = baserom.get_prop("ro.vendor.oplus.regionmark")
        
        # LCD Density
        self.base_rom_density = baserom.get_prop("ro.sf.lcd_density")
        if not self.base_rom_density:
            self.base_rom_density = "480"
        
        # === Port ROM Properties ===
        self.port_android_version = portrom.get_prop("ro.build.version.release")
        self.port_android_sdk = portrom.get_prop("ro.system.build.version.sdk")
        
        self.port_chipset_family = portrom.get_prop("ro.build.device_family")
        
        port_device_code = portrom.get_prop("ro.oplus.version.my_manifest")
        if port_device_code:
            self.port_device_code = port_device_code.split('_')[0]
        
        self.port_product_device = portrom.get_prop("ro.product.device")
        self.port_product_name = portrom.get_prop("ro.product.name")
        self.port_product_model = portrom.get_prop("ro.product.model")
        
        self.port_my_product_type = portrom.get_prop("ro.oplus.image.my_product.type")
        
        # Display ID with replacement
        target_display_id_orig = portrom.get_prop("ro.build.display.id")
        if target_display_id_orig and self.port_device_code and self.base_device_code:
            self.target_display_id = target_display_id_orig.replace(self.port_device_code, self.base_device_code)
        else:
            self.target_display_id = target_display_id_orig
        
        # Vendor brand
        self.port_vendor_brand = portrom.get_prop("ro.product.vendor.brand")
        
        # Area and brand
        self.port_area = portrom.get_prop("ro.oplus.image.system_ext.area")
        self.port_brand = portrom.get_prop("ro.oplus.image.system_ext.brand")
        
        # ROM type detection
        self.portIsRealmeUI = (self.port_brand == "realme")
        self.portIsColorOSGlobal = (self.port_area == "gdpr" and self.port_brand != "oneplus")
        self.portIsOOS = (self.port_area == "gdpr" and self.port_brand == "oneplus")
        self.portIsColorOS = not (self.portIsColorOSGlobal or self.portIsOOS or self.portIsRealmeUI)
        
        # Security patch
        self.security_patch = portrom.get_prop("ro.build.version.security_patch")
        
        # AB device
        is_ab = baserom.get_prop("ro.build.ab_update")
        self.is_ab_device = (is_ab == "true")
        
        # ROM version
        port_rom_version = portrom.get_prop("ro.build.display.ota")
        if port_rom_version:
            self.target_rom_version = port_rom_version.split('_', 1)[1] if '_' in port_rom_version else port_rom_version
        
        self.logger.info(f"Base: Android {self.base_android_version}, SDK {self.base_android_sdk}, Code {self.base_device_code}")
        self.logger.info(f"Port: Android {self.port_android_version}, SDK {self.port_android_sdk}, Code {self.port_device_code}")

    def get_target_prop_file(self, partition_name: str):
        """Get build.prop file path for a target partition"""
        prop_path = self.target_dir / partition_name / "build.prop"
        if prop_path.exists():
            return prop_path
        # Try nested path
        prop_path_nested = self.target_dir / partition_name / partition_name / "build.prop"
        if prop_path_nested.exists():
            return prop_path_nested
        return None

    def _init_workspace(self):
        # if self.build_dir.exists():
        #     shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.repack_dir.mkdir(parents=True, exist_ok=True)
        self.target_config_dir.mkdir(parents=True, exist_ok=True)
        self.repack_images_dir.mkdir(parents=True, exist_ok=True)

    def install_partitions(self):
        # Use ThreadPoolExecutor for parallel partition installation
        max_workers = 4
        
        partition_list = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for part in self.config.possible_super_list:
                 partition_list.append(part)
                 if part in self.config.partition_to_port:
                     futures.append(executor.submit(self._copy_partition, part, self.portrom))
                 else:
                     futures.append(executor.submit(self._copy_partition, part, self.baserom))
         
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"Partition install failed: {e}")
                    pass
        
        # Note: Firmware images are already copied in main.py before this

    def _copy_partition(self, partition, source_rom):
        # 1. Extract to internal source directory first (e.g. build/baserom/extracted/system)
        src_dir = source_rom.extract_partition_to_file(partition)
        
        if not src_dir or not src_dir.exists():
            return

        dest_dir = self.target_dir / partition
        
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        
        # 2. Copy partition files to target directory
        # Copy content of src_dir, not src_dir itself
        shutil.copytree(src_dir, dest_dir, symlinks=True, dirs_exist_ok=True)
        
        # 3. Copy partition configuration files to target_config_dir for Packer
        # (Since extract_partition_to_file moved them out to source_rom/config)
        src_fs, src_fc = source_rom.get_config_files(partition)
        
        if src_fs.exists():
             shutil.copy2(src_fs, self.target_config_dir / f"{partition}_fs_config")
             
        if src_fc.exists():
             shutil.copy2(src_fc, self.target_config_dir / f"{partition}_file_contexts")
