import argparse
import logging
import sys
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.context import Context
from src.core.tools import ToolManager

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

def main():
    args = parse_args()
    
    # Load configuration
    try:
        config = Config.load(args.device_code)
        logger.info(f"Loaded configuration for device: {args.device_code if args.device_code else 'common'}")
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

    # Initialize Context
    logger.info("Initializing Porting Context...")
    ctx = Context(config, baserom, portrom, work_dir) 
    
    # Start Porting Process
    logger.info("Starting porting process...")
    ctx.install_partitions()
    
    logger.info("Porting process (Stage 1: Partition Installation) complete.")

if __name__ == "__main__":
    main()
