import shutil
from pathlib import Path
from src.core.config import Config
from src.core.rom import RomPackage

class Context:
    def __init__(self, config: Config, baserom: RomPackage, portrom: RomPackage, work_dir: str):
        self.config = config
        self.baserom = baserom
        self.portrom = portrom
        self.work_dir = Path(work_dir).resolve()
        
        self.build_dir = self.work_dir / "build"
        self.target_dir = self.build_dir / "target"
        self.repack_dir = self.build_dir / "repack"

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
        source_rom.extract_partition(partition, target_path)
