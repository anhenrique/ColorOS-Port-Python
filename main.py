import argparse
import logging
import sys
import re
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.context import Context
from src.core.tools import ToolManager
from src.core.props import PropertyModifier
from src.core.modifier import SystemModifier, FrameworkModifier
from src.core.packer import Repacker

logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="ColorOS Porting Tool")
    parser.add_argument("--baserom", required=True, help="Path to Base ROM")
    parser.add_argument("--portrom", required=True, help="Path to Port ROM")
    parser.add_argument("--device_code", help="Device code for configuration override")
    parser.add_argument("--work_dir", default="build", help="Working directory")
    parser.add_argument("--pack_type", choices=["super", "payload"], default="payload", help="Output format: super (Fastboot) or payload (OTA). Default: payload")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()

def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')

def detect_device_code(rom_path: str, args_device_code: str | None = None) -> str | None:
    # Priority 1: User Argument
    if args_device_code:
        return args_device_code
    
    # Priority 2: Filename pattern "ColorOS_<CODE>_..."
    filename = Path(rom_path).name
    match = re.search(r"ColorOS_([^_]+)_", filename)
    if match:
        code = match.group(1)
        logger.info(f"Detected device code from filename: {code}")
        return code
    
    # Priority 3: Fallback (original script default: op8t)
    return None

def main():
    args = parse_args()
    
    # Setup logging based on debug flag
    setup_logging(args.debug)
    
    # 1. Initial Device Code Detection (Filename/Args)
    device_code = detect_device_code(args.baserom, args.device_code)
    
    # Load configuration
    try:
        config = Config.load(device_code)
        logger.info(f"Loaded configuration for device: {device_code if device_code else 'common (initial)'}")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Tools
    tools = ToolManager(Path("bin").resolve())

    # Initialize ROM Packages
    logger.info("Initializing ROM packages...")
    baserom = RomPackage(args.baserom, work_dir / "baserom", "BaseROM")
    portrom = RomPackage(args.portrom, work_dir / "portrom", "PortROM")

    # Extract ROMs
    try:
        # Base ROM needs all partitions (including firmware)
        baserom.extract_images()
        
        # Create repack_images directory before copying
        repack_images_dir = work_dir / "repack_images"
        repack_images_dir.mkdir(parents=True, exist_ok=True)
        
        # Extract baserom firmware images (boot, dtbo, etc.) to repack_images_dir
        logger.info("Extracting baserom firmware images...")
        baserom_firmware = ["boot", "dtbo", "vbmeta", "vbmeta_system", "vbmeta_vendor"]
        for fw in baserom_firmware:
            fw_img = baserom.images_dir / f"{fw}.img"
            if fw_img.exists():
                import shutil
                shutil.copy2(fw_img, repack_images_dir / fw_img.name)
                logger.info(f"Copied {fw_img.name} to repack_images")
        
        # Also extract any other .img files from baserom that might be needed
        for fw_img in baserom.images_dir.glob("*.img"):
            dest = repack_images_dir / fw_img.name
            if not dest.exists():
                import shutil
                shutil.copy2(fw_img, dest)
        
        # Port ROM only needs specific partitions from config
        portrom_partitions = config.partition_to_port
        portrom.extract_images(portrom_partitions)
        
        # Also extract baserom partitions needed for props reading
        baserom_partitions = ["system", "product", "system_ext", "my_product", "my_manifest"]
        for part in baserom_partitions:
            baserom.extract_partition_to_file(part)
    except Exception as e:
        logger.error(f"Failed to extract ROMs: {e}")
        sys.exit(1)
    
    # 2. Refined Device Code Detection (After Extraction)
    if not device_code:
        manifest_prop = baserom.images_dir / "my_manifest/build.prop"
        if manifest_prop.exists():
            try:
                with open(manifest_prop, 'r', errors='ignore') as f:
                    for line in f:
                        if "ro.oplus.version.my_manifest=" in line:
                            val = line.split('=')[1].strip()
                            device_code = val.split('_')[0]
                            logger.info(f"Detected device code from build.prop: {device_code}")
                            break
            except Exception as e:
                logger.warning(f"Could not read device code from manifest: {e}")
        
        # If successfully detected now, reload config
        if device_code:
            try:
                config = Config.load(device_code)
                logger.info(f"Reloaded configuration for detected device: {device_code}")
            except Exception as e:
                logger.warning(f"Failed to reload config for {device_code}, using common config.")

    # Initialize Context with finalized config
    logger.info("Initializing Porting Context...")
    # Pass device_code to Context
    ctx = Context(config, baserom, portrom, work_dir, device_code) 
    
    # Stage 1: Install Partitions
    logger.info("Starting Stage 1: Partition Installation...")
    ctx.install_partitions()
    
    # Export build.prop for debugging (after partitions are extracted)
    logger.info("Exporting build.prop for debugging...")
    baserom.export_props(work_dir / "build_props" / "baserom_build.prop")
    portrom.export_props(work_dir / "build_props" / "portrom_build.prop")
    
    # Stage 2: Property Modification
    logger.info("Starting Stage 2: Property Modification...")
    prop_modifier = PropertyModifier(ctx)
    prop_modifier.run()

    # Stage 3: Smali Patching
    logger.info("Starting Stage 3: Smali Patching...")
    system_modifier = SystemModifier(ctx)
    system_modifier.run()
    framework_modifier = FrameworkModifier(ctx)
    framework_modifier.run()

    # Stage 4: Repacking
    logger.info("Starting Stage 4: Repacking...")
    packer = Repacker(ctx)
    
    # Determine pack format
    pack_type = args.pack_type.upper()
    if pack_type == "SUPER":
        packer.pack_all(pack_type="EROFS", is_rw=False)
        packer.pack_super_image()
        logger.info("Super image packing complete.")
    else:
        # Payload format (OTA)
        packer.pack_all(pack_type="EROFS", is_rw=False)
        packer.pack_ota_payload()
        logger.info("OTA payload packing complete.")

    logger.info("Porting process (Stage 1-4) complete.")

if __name__ == "__main__":
    main()
