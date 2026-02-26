#!/usr/bin/env python3
"""
Debug script to test main.py without running full process
Usage: python3 debug_main.py --baserom <path> --portrom <path> [other options]
"""
import sys
import traceback
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test if all imports work correctly"""
    print("Testing imports...")
    try:
        from src.core.config import Config
        from src.core.rom import RomPackage
        from src.core.context import Context
        from src.core.tools import ToolManager
        from src.core.props import PropertyModifier
        from src.core.modifier import SystemModifier, FrameworkModifier, FirmwareModifier
        from src.core.packer import Repacker
        from src.utils.progress import timed_stage, get_timer, create_progress_tracker
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        traceback.print_exc()
        return False

def test_progress_module():
    """Test progress module functionality"""
    print("\nTesting progress module...")
    try:
        from src.utils.progress import get_timer, create_progress_tracker, timed_stage
        import logging
        logging.basicConfig(level=logging.INFO)
        
        # Test timer
        timer = get_timer()
        timer.start_stage("Test Stage")
        import time
        time.sleep(0.1)
        timer.end_stage()
        print("✓ Timer works")
        
        # Test progress tracker
        tracker = create_progress_tracker(total=5, description="Test", unit="items")
        for i in range(5):
            tracker.update(message=f"Item {i}")
        tracker.finish()
        print("✓ Progress tracker works")
        
        # Test context manager
        with timed_stage("Test Context Manager"):
            time.sleep(0.1)
        print("✓ Timed stage context manager works")
        
        print(timer.get_summary())
        return True
    except Exception as e:
        print(f"✗ Progress module test failed: {e}")
        traceback.print_exc()
        return False

def test_rom_package_init(baserom_path: str, portrom_path: str):
    """Test RomPackage initialization"""
    print(f"\nTesting RomPackage initialization...")
    try:
        from src.core.rom import RomPackage
        from pathlib import Path
        
        work_dir = Path("build")
        
        print(f"  Creating BaseROM package from: {baserom_path}")
        baserom = RomPackage(baserom_path, work_dir / "baserom", "BaseROM")
        print(f"  ✓ BaseROM created: {baserom.rom_type}")
        
        print(f"  Creating PortROM package from: {portrom_path}")
        portrom = RomPackage(portrom_path, work_dir / "portrom", "PortROM")
        print(f"  ✓ PortROM created: {portrom.rom_type}")
        
        return True
    except Exception as e:
        print(f"✗ RomPackage initialization failed: {e}")
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description="Debug main.py issues")
    parser.add_argument("--baserom", help="Path to Base ROM (optional for basic tests)")
    parser.add_argument("--portrom", help="Path to Port ROM (optional for basic tests)")
    parser.add_argument("--full", action="store_true", help="Run full tests including ROM initialization")
    args = parser.parse_args()
    
    print("="*60)
    print("ColorOS Porting Tool - Debug Script")
    print("="*60)
    
    # Always run basic tests
    success = True
    success = test_imports() and success
    success = test_progress_module() and success
    
    # Run ROM tests if paths provided
    if args.full and args.baserom and args.portrom:
        success = test_rom_package_init(args.baserom, args.portrom) and success
    elif args.full:
        print("\n⚠ Skipping ROM tests: --baserom and --portrom required")
    
    print("\n" + "="*60)
    if success:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
    print("="*60)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
