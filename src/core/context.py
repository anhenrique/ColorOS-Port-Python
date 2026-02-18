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
        self.work_dir = Path(work_dir).resolve()
        self.device_code = device_code
        self.logger = logger
        
        self.build_dir = self.work_dir
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
        # Use ThreadPoolExecutor for parallel partition installation
        max_workers = 4
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for part in self.config.possible_super_list:
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

    def _copy_partition(self, partition, source_rom):
        # 1. Extract to internal source directory first (e.g. build/baserom/extracted/system)
        src_dir = source_rom.extract_partition_to_file(partition, self.tools)
        
        if not src_dir or not src_dir.exists():
            return

        dest_dir = self.target_dir / partition
        
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        
        # 2. Copy partition files to target directory
        # shutil.copytree(src, dst)
        shutil.copytree(src_dir, dest_dir, symlinks=True, dirs_exist_ok=True)
        
        # 3. Copy partition configuration files BACK into target dir for Packer
        # (Since extract_partition_to_file moved them out to source_rom/config)
        src_fs, src_fc = source_rom.get_config_files(partition)
        
        if src_fs.exists():
             shutil.copy2(src_fs, dest_dir / f"{partition}_fs_config")
             
        if src_fc.exists():
             shutil.copy2(src_fc, dest_dir / f"{partition}_file_contexts")

