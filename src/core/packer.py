import logging
import os
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
        
        # 1. Pack individual partitions
        self._pack_partitions()
        
        # 2. Pack Super Image (if configured or requested)
        # Check if we need to pack super
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
            
            # Determine method
            method = self.config.pack_method # "erofs" or "ext4"
            
            if method == "erofs":
                self._pack_erofs(partition_dir, output_img, part_name)
            elif method == "ext4":
                self._pack_ext4(partition_dir, output_img, part_name)
            else:
                logger.warning(f"Unknown pack method {method}, defaulting to erofs")
                self._pack_erofs(partition_dir, output_img, part_name)

    def _pack_erofs(self, mount_point, output_file, partition_name):
        # mkfs.erofs -zlz4hc -T 1230768000 --mount-point /partition_name --fs-config-file ... ...
        tool = self.tools.get_tool("mkfs.erofs")
        
        # fs_config and file_contexts handling
        # Usually we need to generate these or use existing ones.
        # For this basic implementation, we might skip fs-config if not available, 
        # or assume standard android perms.
        # However, erofs usually requires them for proper permissions.
        # HyperOS-Port uses fs_config_generator or similar. 
        # The original script might use --fs-config-file if available.
        
        # Construct command
        # Simplified:
        cmd = f"{tool} -zlz4hc -T 1230768000 --mount-point /{partition_name} "
        
        # Check for fs_config/file_contexts in config dir if we had one
        # For now, let's try to run without specific fs-config (will use current user/group, which is bad for Android)
        # TODO: Implement fs_config generation or reading from source ROM
        
        # Using --ugid-map or similar if available? 
        # Or relying on the fact that we might have preserved perms if we were root?
        # We are likely not root.
        # We NEED fs_config to set uid/gid/capabilities.
        
        # Placeholder for full implementation:
        cmd += f"{output_file} {mount_point}"
        
        Shell.run(cmd)

    def _pack_ext4(self, mount_point, output_file, partition_name):
        # make_ext4fs -J -T 1230768000 -S file_contexts -l size ...
        tool = self.tools.get_tool("make_ext4fs")
        # Same issue with file_contexts/fs_config
        pass

    def pack_super(self):
        # lpmake ...
        pass
