import shutil
import logging
import concurrent.futures
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.tools import ToolManager
from src.utils.shell import ShellRunner
from src.utils.assets import AssetManager

logger = logging.getLogger(__name__)


class Context:
    def __init__(
        self,
        config: Config,
        baserom: RomPackage,
        portrom: RomPackage,
        work_dir: str | Path,
        device_code: str | None = None,
    ):
        self.config = config
        self.baserom = baserom
        self.portrom = portrom

        # Compatibility aliases for modifier.py
        self.stock = baserom
        self.port = portrom

        self.work_dir = Path(work_dir).resolve()
        self.device_code = device_code
        self.stock_rom_code = device_code

        self.assets = AssetManager(self.config.assets_base_url)

        # Configuration properties
        self.enable_ksu = config.enable_ksu
        self.ksu_type = config.ksu_type
        self.disable_vbmeta = config.disable_vbmeta

        # Target properties (derived from base/port ROMs)
        self._target_device_code = None
        self._target_display_id = None
        self._target_rom_version = "1.0"

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

    # === Compatibility properties (delegate to RomPackage) ===

    # Base ROM properties
    @property
    def base_android_version(self): return self.baserom.android_version
    @property
    def base_android_sdk(self): return self.baserom.android_sdk
    @property
    def base_device_code(self): return self.baserom.device_code
    @property
    def base_product_device(self): return self.baserom.product_device
    @property
    def base_product_name(self): return self.baserom.product_name
    @property
    def base_product_model(self): return self.baserom.product_model
    @property
    def base_vendor_device(self): return self.baserom.vendor_device
    @property
    def base_vendor_model(self): return self.baserom.vendor_model
    @property
    def base_vendor_brand(self): return self.baserom.vendor_brand
    @property
    def base_chipset_family(self): return self.baserom.chipset_family
    @property
    def base_market_name(self): return self.baserom.market_name
    @property
    def base_market_enname(self): return self.baserom.market_enname
    @property
    def base_regionmark(self): return self.baserom.region_mark
    @property
    def base_rom_density(self): return self.baserom.lcd_density
    @property
    def base_my_product_type(self): return self.baserom.my_product_type

    # Port ROM properties
    @property
    def port_android_version(self): return self.portrom.android_version
    @property
    def port_android_sdk(self): return self.portrom.android_sdk
    @property
    def port_device_code(self): return self.portrom.device_code
    @property
    def port_product_device(self): return self.portrom.product_device
    @property
    def port_product_name(self): return self.portrom.product_name
    @property
    def port_product_model(self): return self.portrom.product_model
    @property
    def port_vendor_device(self): return self.portrom.vendor_device
    @property
    def port_vendor_model(self): return self.portrom.vendor_model
    @property
    def port_vendor_brand(self): return self.portrom.vendor_brand
    @property
    def port_chipset_family(self): return self.portrom.chipset_family
    @property
    def port_market_name(self): return self.portrom.market_name
    @property
    def port_my_product_type(self): return self.portrom.my_product_type
    @property
    def port_area(self): return self.portrom.area
    @property
    def port_brand(self): return self.portrom.brand
    @property
    def port_oplusrom_version(self): return self.portrom.oplusrom_version
    @property
    def port_is_realme_ui(self): return self.portrom.is_realme_ui
    @property
    def port_is_coloros_global(self): return self.portrom.is_coloros_global
    @property
    def port_is_oos(self): return self.portrom.is_oos
    @property
    def port_is_coloros(self): return self.portrom.is_coloros

    # Target properties
    @property
    def target_device_code(self):
        """Target device code (from base ROM)"""
        return self._target_device_code or self.base_device_code

    @target_device_code.setter
    def target_device_code(self, value):
        self._target_device_code = value

    @property
    def target_display_id(self):
        """Target display ID (port display with base device code)"""
        if self._target_display_id is None:
            port_display = self.portrom.display_id
            if port_display and self.port_device_code and self.base_device_code:
                self._target_display_id = port_display.replace(
                    self.port_device_code, self.base_device_code
                )
            else:
                self._target_display_id = port_display
        return self._target_display_id

    @property
    def target_rom_version(self):
        """Target ROM version (from port OTA display)"""
        if self._target_rom_version == "1.0":
            port_ota = self.portrom.display_ota
            if port_ota:
                self._target_rom_version = (
                    port_ota.split("_", 1)[1] if "_" in port_ota else port_ota
                )
        return self._target_rom_version

    @property
    def security_patch(self): return self.portrom.security_patch
    @property
    def is_ab_device(self): return self.baserom.is_ab_device

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
        """Fetch and log ROM properties (now delegated to RomPackage properties)"""
        self.logger.info("Fetching ROM properties...")

        # Access properties to trigger caching and logging
        self.logger.info(
            f"Base: Android {self.base_android_version}, SDK {self.base_android_sdk}, Code {self.base_device_code}"
        )
        self.logger.info(
            f"Port: Android {self.port_android_version}, SDK {self.port_android_sdk}, Code {self.port_device_code}"
        )

    def get_target_prop_file(self, partition_name: str):
        """Get build.prop file path for a target partition"""
        prop_path = self.target_dir / partition_name / "build.prop"
        if prop_path.exists():
            return prop_path
        # Try nested path
        prop_path_nested = (
            self.target_dir / partition_name / partition_name / "build.prop"
        )
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
        import os

        max_workers = os.cpu_count() or 4

        self.logger.info(f"Installing partitions using {max_workers} threads...")
        partition_list = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for part in self.config.possible_super_list:
                partition_list.append(part)
                if part in self.config.partition_to_port:
                    futures.append(
                        executor.submit(self._copy_partition, part, self.portrom)
                    )
                else:
                    futures.append(
                        executor.submit(self._copy_partition, part, self.baserom)
                    )

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
        self.logger.info(
            f"[{source_rom.label}] Installing partition: {partition} -> {dest_dir.relative_to(self.work_dir)}"
        )

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        # 2. Copy partition files to target directory
        # Use native 'cp -af' for better performance and preservation of links/attrs
        dest_dir.mkdir(parents=True, exist_ok=True)
        # cp -af src_dir/. dest_dir/ ensures contents are copied into dest_dir
        cmd = f"cp -af {src_dir}/. {dest_dir}/"
        try:
            shell = ShellRunner()
            shell.run(cmd)
        except Exception as e:
            self.logger.error(f"Failed to copy partition {partition}: {e}")
            # Fallback to shutil if native cp fails
            shutil.copytree(src_dir, dest_dir, symlinks=True, dirs_exist_ok=True)

        # 3. Copy partition configuration files to target_config_dir for Packer
        # (Since extract_partition_to_file moved them out to source_rom/config)
        src_fs, src_fc = source_rom.get_config_files(partition)

        if src_fs.exists():
            shutil.copy2(src_fs, self.target_config_dir / f"{partition}_fs_config")

        if src_fc.exists():
            shutil.copy2(src_fc, self.target_config_dir / f"{partition}_file_contexts")
