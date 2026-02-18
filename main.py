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
from src.core.patcher import SmaliPatcher
from src.core.packer import Packer

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="ColorOS Porting Tool")
    parser.add_argument("--baserom", required=True, help="Path to Base ROM")
    parser.add_argument("--portrom", required=True, help="Path to Port ROM")
    parser.add_argument("--device_code", help="Device code for configuration override")
    parser.add_argument("--work_dir", default="build", help="Working directory")
    return parser.parse_args()

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
        baserom.extract(tools)
        portrom.extract(tools)
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
    ctx = Context(config, baserom, portrom, work_dir) 
    
    # Stage 1: Install Partitions
    logger.info("Starting Stage 1: Partition Installation...")
    ctx.install_partitions()
    
    # Stage 2: Property Modification
    logger.info("Starting Stage 2: Property Modification...")
    prop_modifier = PropertyModifier(ctx)
    prop_modifier.run()

    # Stage 3: Smali Patching
    logger.info("Starting Stage 3: Smali Patching...")
    patcher = SmaliPatcher(ctx)
    patcher.run()

    # Stage 4: Repacking
    logger.info("Starting Stage 4: Repacking...")
    packer = Packer(ctx)
    packer.run()

    logger.info("Porting process (Stage 1-4) complete.")

if __name__ == "__main__":
    main()
