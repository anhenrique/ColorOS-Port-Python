import shutil
from pathlib import Path
import platform
import logging

logger = logging.getLogger(__name__)

class ToolManager:
    def __init__(self, bin_root: Path):
        self.bin_root = bin_root.resolve()
        self.system = platform.system().lower()
        self.machine = platform.machine().lower()
        self._init_paths()

    def _init_paths(self):
        # Determine architecture
        if self.machine in ["amd64", "x86_64"]:
            arch = "x86_64"
        elif self.machine in ["aarch64", "arm64"]:
            arch = "arm64"
        else:
            arch = "x86_64" # Default fallback

        # Determine OS subdirectory
        if self.system == "linux":
            plat_dir = "linux"
        elif self.system == "windows":
            plat_dir = "windows"
        elif self.system == "darwin":
            plat_dir = "macos"
        else:
            plat_dir = "linux"

        self.platform_bin = self.bin_root / plat_dir / arch
        self.apktool_bin = self.bin_root / "apktool"
        
        logger.info(f"Platform tools path: {self.platform_bin}")

    def get_tool(self, tool_name: str) -> str:
        # Search priority: 
        # 1. bin/linux/x86_64/tool_name
        # 2. bin/apktool/tool_name
        # 3. System PATH
        
        # Check platform bin
        tool_path = self.platform_bin / tool_name
        if tool_path.exists():
            return str(tool_path)
            
        # Check apktool bin
        tool_path = self.apktool_bin / tool_name
        if tool_path.exists():
            return str(tool_path)
        
        # Check system path
        system_tool = shutil.which(tool_name)
        if system_tool:
            return system_tool
            
        logger.warning(f"Tool {tool_name} not found in project binaries or system PATH.")
        return tool_name  # Return bare name and hope for the best

# Singleton instance placeholder - will be initialized in Context
