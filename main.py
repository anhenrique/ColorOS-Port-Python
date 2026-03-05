import argparse
import logging
import sys
import re
import shutil
import zipfile
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.context import Context
from src.core.tools import ToolManager
from src.core.props import PropertyModifier
from src.core.modifier import SystemModifier, FrameworkModifier, FirmwareModifier
from src.core.packer import Repacker
from src.utils.progress import timed_stage, get_timer, create_progress_tracker
from src.utils.perf_monitor import get_monitor, reset_monitor

logger = logging.getLogger(__name__)

# Define logical partitions as a constant
LOGICAL_PARTITIONS = {
    "system",
    "vendor",
    "product",
    "system_ext",
    "odm",
    "mi_ext",
    "my_product",
    "my_manifest",
    "my_stock",
    "my_region",
    "my_carrier",
    "my_heytap",
    "my_bigball",
    "my_engineering",
    "vendor_dlkm",
    "odm_dlkm",
    "system_dlkm",
    "product_dlkm",
}


def parse_args():
    parser = argparse.ArgumentParser(description="ColorOS Porting Tool")
    parser.add_argument("--baserom", required=True, help="Path to Base ROM")
    parser.add_argument("--portrom", required=True, help="Path to Port ROM")
    parser.add_argument("--device_code", help="Device code for configuration override")
    parser.add_argument("--work_dir", default="build", help="Working directory")
    parser.add_argument(
        "--clean", action="store_true", help="Clean working directory before starting"
    )
    parser.add_argument(
        "--pack_type",
        choices=["super", "payload"],
        default="payload",
        help="Output format: super (Fastboot) or payload (OTA). Default: payload",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def setup_logging(work_dir: Path, debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO

    # Create work_dir if not exists
    work_dir.mkdir(parents=True, exist_ok=True)
    log_file = work_dir / "port.log"

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers = []

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File Handler
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logger.info(f"Logging initialized. Log file: {log_file}")


def clean_work_dir(work_dir: Path):
    if work_dir.exists():
        logger.warning(f"Cleaning working directory: {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)


def detect_device_code(
    rom_path: str, args_device_code: str | None = None
) -> str | None:
    # Priority 1: User Argument
    if args_device_code:
        return args_device_code

    # Priority 2: Read from ZIP metadata file
    try:
        with zipfile.ZipFile(rom_path, "r") as zf:
            metadata_path = "META-INF/com/android/metadata"
            if metadata_path in zf.namelist():
                with zf.open(metadata_path) as f:
                    content = f.read().decode("utf-8")
                    match = re.search(r"pre-device=(\S+)", content)
                    if match:
                        code = match.group(1)
                        logger.info(f"Detected device code from metadata: {code}")
                        return code
    except Exception as e:
        logger.debug(f"Failed to read metadata from ZIP: {e}")

    # Priority 3: Filename pattern "ColorOS_<CODE>_..."
    filename = Path(rom_path).name
    match = re.search(r"ColorOS_([^_]+)_", filename)
    if match:
        code = match.group(1)
        logger.info(f"Detected device code from filename: {code}")
        return code

    # Priority 4: Fallback
    return None


def copy_firmware_images(baserom: RomPackage, repack_images_dir: Path) -> int:
    """Copy firmware images from baserom to repack_images directory.

    Returns:
        Number of images copied
    """
    logger.info("Copying baserom firmware images...")

    # Collect all firmware images from multiple sources
    fw_images = []

    # 1. Copy images from firmware-update directory (Brotli format)
    firmware_update_dir = baserom.images_dir / "firmware-update"
    if firmware_update_dir.exists():
        fw_images.extend(list(firmware_update_dir.glob("*.img")))

    # 2. Copy storage-fw.img if exists (for some devices)
    storage_fw = baserom.images_dir / "storage-fw.img"
    if storage_fw.exists():
        fw_images.append(storage_fw)

    # 3. Copy other firmware images from images root (non-logical partitions)
    for img in baserom.images_dir.glob("*.img"):
        part_name = img.stem.replace("_a", "").replace("_b", "")
        if part_name not in LOGICAL_PARTITIONS:
            fw_images.append(img)

    if not fw_images:
        logger.warning("No firmware images found in baserom images directory")
        return 0

    # Create progress tracker
    tracker = create_progress_tracker(
        total=len(fw_images), description="Copying firmware", unit="images"
    )

    copied_count = 0
    for fw_img in fw_images:
        try:
            part_name = fw_img.stem.replace("_a", "").replace("_b", "")

            if part_name in LOGICAL_PARTITIONS:
                tracker.update(message=f"Skipped {fw_img.name} (logical partition)")
                continue

            dest = repack_images_dir / fw_img.name
            shutil.copy2(fw_img, dest)
            copied_count += 1
            tracker.update(message=f"Copied {fw_img.name}")
        except Exception as e:
            logger.error(f"Failed to copy {fw_img.name}: {e}")
            tracker.update(message=f"Failed {fw_img.name}: {e}")

    tracker.finish()
    return copied_count


def extract_baserom_partitions(baserom: RomPackage, partitions: list[str]):
    """Extract baserom partitions with progress tracking."""
    tracker = create_progress_tracker(
        total=len(partitions),
        description="Extracting BaseROM partitions",
        unit="partitions",
    )

    for part in partitions:
        try:
            result = baserom.extract_partition_to_file(part)
            if result:
                tracker.update(message=f"Extracted {part}")
            else:
                tracker.update(message=f"Skipped {part} (not found)")
        except Exception as e:
            logger.warning(f"Failed to extract {part}: {e}")
            tracker.update(message=f"Failed {part}: {e}")

    tracker.finish()


def main():
    args = parse_args()
    work_dir = Path(args.work_dir).resolve()

    # Setup logging based on debug flag and work_dir
    setup_logging(work_dir, args.debug)

    # Clean working directory if requested
    if args.clean:
        clean_work_dir(work_dir)

    # Reset and get global timer
    from src.utils.progress import reset_timer

    reset_timer()
    timer = get_timer()

    # Initialize performance monitor
    reset_monitor()
    monitor = get_monitor()

    try:
        with timed_stage("Initialization"):
            # Log initial resource status
            monitor.log_resource_status("Initialization")

            # 1. Initial Device Code Detection (Filename/Args)
            device_code = detect_device_code(args.baserom, args.device_code)

            # Load configuration
            try:
                config = Config.load(device_code)
                logger.info(
                    f"Loaded configuration for device: {device_code if device_code else 'common (initial)'}"
                )
            except Exception as e:
                logger.error(f"Failed to load configuration: {e}")
                sys.exit(1)

            # Initialize Tools
            tools = ToolManager(Path("bin").resolve())

            # Initialize ROM Packages
            logger.info("Initializing ROM packages...")
            baserom = RomPackage(args.baserom, work_dir / "baserom", "BaseROM")
            portrom = RomPackage(args.portrom, work_dir / "portrom", "PortROM")

        with timed_stage("ROM Extraction"):
            # Extract ROMs
            try:
                # Base ROM needs all partitions (including firmware)
                baserom.extract_images()

                # Create repack_images directory before copying
                repack_images_dir = work_dir / "repack_images"
                repack_images_dir.mkdir(parents=True, exist_ok=True)

                # Copy firmware images from baserom to repack_images (only for PAYLOAD format)
                # For BROTLI format, firmware is in firmware-update/ directory and handled separately
                if baserom.rom_type.name == "PAYLOAD":
                    copied_count = copy_firmware_images(baserom, repack_images_dir)
                    logger.info(
                        f"Copied {copied_count} firmware images to repack_images"
                    )
                else:
                    logger.info("Skipping firmware copy for non-PAYLOAD format")

                # Port ROM only needs specific partitions from config
                portrom_partitions = config.partition_to_port
                portrom.extract_images(portrom_partitions)

                # Also extract baserom partitions needed for props reading
                baserom_partitions = [
                    "system",
                    "product",
                    "system_ext",
                    "my_product",
                    "my_manifest",
                ]
                extract_baserom_partitions(baserom, baserom_partitions)

            except Exception as e:
                logger.error(f"Failed to extract ROMs: {e}")
                sys.exit(1)

        with timed_stage("Device Detection & Context Setup"):
            # 2. Refined Device Code Detection (After Extraction)
            # Use ro.product.vendor.device as the unique device identifier (base_device)
            # This is the device code used to find configuration in devices/target/
            if not device_code or device_code == "common":
                base_device = baserom.get_prop("ro.product.vendor.device")
                if base_device:
                    device_code = base_device.strip().replace(" ", "").upper()
                    logger.info(
                        f"Detected base_device from ro.product.vendor.device: {device_code}"
                    )

                if device_code:
                    try:
                        config = Config.load(device_code)
                        logger.info(
                            f"Reloaded configuration for detected device: {device_code}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"No specific config for {device_code}, continuing with current config."
                        )

            # Initialize Context with finalized config
            logger.info("Initializing Porting Context...")
            ctx = Context(config, baserom, portrom, work_dir, device_code)

        with timed_stage("Stage 1: Partition Installation"):
            logger.info("Starting Stage 1: Partition Installation...")
            ctx.install_partitions()

        with timed_stage("Export Build Props"):
            logger.info("Exporting build.prop for debugging...")
            baserom.export_props(work_dir / "build_props" / "baserom_build.prop")
            portrom.export_props(work_dir / "build_props" / "portrom_build.prop")

        with timed_stage("Stage 2: Property Modification"):
            logger.info("Starting Stage 2: Property Modification...")
            prop_modifier = PropertyModifier(ctx)
            prop_modifier.run()

        with timed_stage("Stage 3: Smali Patching"):
            logger.info("Starting Stage 3: Smali Patching...")
            system_modifier = SystemModifier(ctx)
            system_modifier.run()
            framework_modifier = FrameworkModifier(ctx)
            framework_modifier.run()

        with timed_stage("Stage 3.5: Firmware Modification"):
            logger.info("Starting Stage 3.5: Firmware Modification (KSU/VBMeta)...")
            fw_modifier = FirmwareModifier(ctx)
            fw_modifier.run()

        with timed_stage("Stage 4: Repacking"):
            logger.info("Starting Stage 4: Repacking...")
            packer = Repacker(ctx)

            pack_type = args.pack_type.upper()
            if pack_type == "SUPER":
                packer.pack_all(pack_type="EROFS", is_rw=False)
                packer.pack_super_image()
                logger.info("Super image packing complete.")
            else:
                packer.pack_all(pack_type="EROFS", is_rw=False)
                packer.pack_ota_payload()
                logger.info("OTA payload packing complete.")

        logger.info("Porting process (Stage 1-4) complete.")

        # Log final resource status
        monitor.log_resource_status("Completed")

        # Print performance summary
        timer.print_summary()
        monitor.print_summary()

    except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
        timer.print_summary()
        monitor.print_summary()
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        timer.print_summary()
        monitor.print_summary()
        sys.exit(1)


if __name__ == "__main__":
    main()
