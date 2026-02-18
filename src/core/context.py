import shutil
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage
from src.core.tools import ToolManager
from src.utils.shell import Shell

class Context:
    def __init__(self, config: Config, baserom: RomPackage, portrom: RomPackage, work_dir: str | Path, device_code: str = None):
        self.config = config
        self.baserom = baserom
        self.portrom = portrom
        self.work_dir = Path(work_dir).resolve()
        self.device_code = device_code
        
        self.build_dir = self.work_dir / "build"
        self.target_dir = self.build_dir / "target"
        self.repack_dir = self.build_dir / "repack"

        # Initialize tools
        self.bin_root = Path("bin").resolve()
        self.tools = ToolManager(self.bin_root)
        
        self._init_workspace()

    def _init_workspace(self):
        # if self.build_dir.exists():
        #     shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.repack_dir.mkdir(parents=True, exist_ok=True)

    def install_partitions(self):
        for part in self.config.possible_super_list:
             if part in self.config.partition_to_port:
                 self._copy_partition(part, self.portrom)
             else:
                 self._copy_partition(part, self.baserom)

    def _copy_partition(self, partition, source_rom):
        target_path = self.target_dir / partition
        # Pass the tool manager to extract_partition so it can find 7z/fsck.erofs
        source_rom.extract_partition(partition, target_path, self.tools)
