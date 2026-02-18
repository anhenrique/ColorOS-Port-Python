import logging
import os
import shutil
from pathlib import Path
from src.core.context import Context
from src.utils.shell import Shell

logger = logging.getLogger(__name__)

class Packer:
    def __init__(self, context: Context):
        self.ctx = context
        self.config = self.ctx.config
        self.target_dir = self.ctx.target_dir
        self.repack_dir = self.ctx.repack_dir
        self.tools = self.ctx.tools

    def run(self):
        logger.info("Starting Repacking Phase...")
        
        # Ensure repack directory exists
        if self.repack_dir.exists():
            shutil.rmtree(self.repack_dir)
        self.repack_dir.mkdir(parents=True, exist_ok=True)

        # 1. Pack individual partitions
        self._pack_partitions()
        
        # 2. Pack Super Image (if needed, logic to be added)
        # self._pack_super()
        
        logger.info("Repacking Complete.")

    def _pack_partitions(self):
        # Iterate over partitions in target_dir
        for partition_dir in self.target_dir.iterdir():
            if not partition_dir.is_dir():
                continue
            
            part_name = partition_dir.name
            logger.info(f"Packing partition: {part_name}")
            
            output_img = self.repack_dir / f"{part_name}.img"
            
            # Determine method (default to erofs if not specified)
            method = self.config.pack_method # "erofs" or "ext4"
            
            if method == "erofs":
                self._pack_erofs(partition_dir, output_img, part_name)
            elif method == "ext4":
                self._pack_ext4(partition_dir, output_img, part_name)
            else:
                logger.warning(f"Unknown pack method {method}, defaulting to erofs")
                self._pack_erofs(partition_dir, output_img, part_name)

    def _pack_erofs(self, mount_point: Path, output_file: Path, partition_name: str):
        # Tool: mkfs.erofs
        tool = self.tools.get_tool("mkfs.erofs")
        
        # Look for fs_config and file_contexts
        # They should have been extracted to work_dir/extracted/config/ or similar
        # But wait, our Context/RomPackage architecture extracted them to:
        # baserom.extracted_dir / config / ...
        # portrom.extracted_dir / config / ...
        # We need to know WHICH ROM this partition came from to find the original config.
        # OR, we should have copied them to a central location in Context.
        
        # Current Context.install_partitions implementation:
        # It calls `source_rom.extract_partition(partition, target_path, tools)`
        # `RomPackage.extract_partition` just extracts the image. It DOES NOT currently handle fs_config/file_contexts extraction explicitly 
        # (unlike the HyperOS reference I saw earlier).
        
        # CRITICAL MISSING PIECE: We need fs_config/file_contexts.
        # For now, we will assume standard Android permissions (using --mount-point) 
        # or try to find them if they were extracted by extract.erofs
        
        # Logic: 
        # 1. extract.erofs -x -o target_dir extracts the image. 
        #    It usually creates `file_contexts` inside the target_dir or parent?
        #    Let's check `RomPackage.extract_partition`: `extract.erofs -i {img} -x -o {target_dir}`
        
        fs_config_file = mount_point / "config" / f"{partition_name}_fs_config" # Hypothetical
        file_contexts_file = mount_point / "config" / f"{partition_name}_file_contexts" # Hypothetical

        # Try to find file_contexts in the root of the extracted partition (common behavior of extraction tools)
        potential_fc = list(mount_point.glob("*file_contexts"))
        real_fc = potential_fc[0] if potential_fc else None
        
        # Command Construction
        # -zlz4hc: Compression
        # -T 1230768000: Fixed timestamp for reproducibility
        # --mount-point: Mount point prefix (e.g. /system)
        
        cmd = [tool, "-zlz4hc", "-T", "1230768000", "--mount-point", f"/{partition_name}"]
        
        if real_fc:
            cmd.extend(["--file-contexts", str(real_fc)])
            
        # fs_config is trickier. Often we need to generate it or use `fs_config` file.
        # For now, we omit --fs-config-file unless we have one.
        
        cmd.extend([str(output_file), str(mount_point)])
        
        # Convert list to string for Shell.run
        cmd_str = " ".join(cmd)
        Shell.run(cmd_str)

    def _pack_ext4(self, mount_point: Path, output_file: Path, partition_name: str):
        # Tool: make_ext4fs
        tool = self.tools.get_tool("make_ext4fs")
        
        # Identify size logic?
        # Usually we need -l <size>. If not provided, it might fail or auto-detect.
        # Ideally we read original size or set a safe large size (if sparse).
        
        # Simplified:
        cmd = [tool, "-J", "-T", "1230768000", "-L", partition_name]
        
        # Check for file_contexts
        potential_fc = list(mount_point.glob("*file_contexts"))
        if potential_fc:
             cmd.extend(["-S", str(potential_fc[0])])
             
        # Size? 
        # Let's try without size (auto) or large size if sparse
        # make_ext4fs -l 4096M ...
        # Safe default for large partitions?
        cmd.extend(["-l", "6000M"]) # Temporary hardcode, normally calculated
        
        cmd.extend([str(output_file), str(mount_point)])
        
        cmd_str = " ".join(cmd)
        Shell.run(cmd_str)
