import logging
import os
import shutil
import re
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
        
        # 2. Pack Super Image
        self._pack_super()
        
        logger.info("Repacking Complete.")

    def _pack_partitions(self):
        for partition_dir in self.target_dir.iterdir():
            if not partition_dir.is_dir():
                continue
            
            part_name = partition_dir.name
            logger.info(f"Packing partition: {part_name}")
            
            output_img = self.repack_dir / f"{part_name}.img"
            
            method = self.config.pack_method
            
            if method == "erofs":
                self._pack_erofs(partition_dir, output_img, part_name)
            elif method == "ext4":
                self._pack_ext4(partition_dir, output_img, part_name)
            else:
                logger.warning(f"Unknown pack method {method}, defaulting to erofs")
                self._pack_erofs(partition_dir, output_img, part_name)

    def _pack_erofs(self, mount_point: Path, output_file: Path, partition_name: str):
        tool = self.tools.get_tool("mkfs.erofs")
        
        # Try to find file_contexts
        potential_fc = list(mount_point.glob("*file_contexts"))
        real_fc = potential_fc[0] if potential_fc else None
        
        cmd = [tool, "-zlz4hc", "-T", "1230768000", "--mount-point", f"/{partition_name}"]
        
        if real_fc:
            cmd.extend(["--file-contexts", str(real_fc)])
            
        cmd.extend([str(output_file), str(mount_point)])
        
        cmd_str = " ".join(cmd)
        logger.info(f"Packing {partition_name} with erofs...")
        
        # Suppress verbose output, only show errors
        import subprocess
        import shlex
        try:
            result = subprocess.run(
                shlex.split(cmd_str),
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error(f"mkfs.erofs failed for {partition_name}: {result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, cmd_str)
            # Only log summary, not all the "Processing..." lines
            if result.stderr:
                logger.warning(f"mkfs.erofs warnings for {partition_name}: {result.stderr}")
            logger.info(f"Successfully packed {partition_name}.img ({output_file.stat().st_size / (1024*1024):.2f} MB)")
        except Exception as e:
            logger.error(f"Failed to pack {partition_name}: {e}")
            raise

    def _pack_ext4(self, mount_point: Path, output_file: Path, partition_name: str):
        tool = self.tools.get_tool("make_ext4fs")
        cmd = [tool, "-J", "-T", "1230768000", "-L", partition_name]
        
        potential_fc = list(mount_point.glob("*file_contexts"))
        if potential_fc:
             cmd.extend(["-S", str(potential_fc[0])])
             
        cmd.extend(["-l", "6000M"]) 
        cmd.extend([str(output_file), str(mount_point)])
        
        cmd_str = " ".join(cmd)
        Shell.run(cmd_str)

    def _pack_super(self):
        logger.info("Packing super.img...")
        
        # 1. Determine size
        device_code = self.ctx.device_code
        super_size = self._get_super_size(device_code)
        logger.info(f"Using super size: {super_size} for device {device_code}")

        # 2. Determine AB status
        is_ab = self._is_ab_device()
        logger.info(f"Is AB Device: {is_ab}")

        # 3. Construct lpmake command
        tool = self.tools.get_tool("lpmake")
        
        # Basic args
        cmd = [tool, "--metadata-size", "65536", "--super-name", "super"]
        
        if is_ab:
            cmd.extend(["--metadata-slots", "3"])
            cmd.extend(["--device", f"super:{super_size}"])
            cmd.extend([f"--group=qti_dynamic_partitions_a:{super_size}"])
            cmd.extend([f"--group=qti_dynamic_partitions_b:{super_size}"])
            cmd.extend(["--virtual-ab"])
        else:
            cmd.extend(["--metadata-slots", "2"])
            cmd.extend(["--device", f"super:{super_size}"])
            cmd.extend([f"--group=qti_dynamic_partitions:{super_size}"])

        # Add partitions
        # Iterate through possible_super_list from config, check if img exists in repack_dir
        for part in self.config.possible_super_list:
            img_path = self.repack_dir / f"{part}.img"
            if not img_path.exists():
                continue
            
            size = img_path.stat().st_size
            logger.info(f"Adding {part} ({size} bytes) to super")
            
            if is_ab:
                # Add _a partition
                cmd.extend([f"--partition", f"{part}_a:none:{size}:qti_dynamic_partitions_a"])
                cmd.extend([f"--image", f"{part}_a={img_path}"])
                # Add _b partition (empty)
                cmd.extend([f"--partition", f"{part}_b:none:0:qti_dynamic_partitions_b"])
            else:
                cmd.extend([f"--partition", f"{part}:none:{size}:qti_dynamic_partitions"])
                cmd.extend([f"--image", f"{part}={img_path}"])

        # Output
        output_super = self.repack_dir / "super.img"
        cmd.extend(["--output", str(output_super)])
        
        # Execute
        cmd_str = " ".join(cmd)
        Shell.run(cmd_str)
        
        if output_super.exists():
            logger.info(f"Successfully created super.img at {output_super}")
        else:
            logger.error("Failed to create super.img")

    def _get_super_size(self, device_code):
        # Default fallback
        default_size = "15032385536"
        
        if not device_code:
            return default_size
            
        sizes = {
            "OnePlus9R": "9932111872",
            "OnePlus8T": "7516192768",
            "OnePlus8": "15032385536",
            "OnePlus8Pro": "15032385536",
            "OP4E5D": "11190403072",
            "OnePlus9": "11190403072",
            "OnePlus9Pro": "11190403072",
            "OP4E3F": "11186208768",
            "OP4F57L1": "11186208768",
            "RE54E4L1": "11274289152",
            "RMX3371": "11274289152",
            "OP5CFBL1": "16106127360",
            "RE5473": "10200547328",
            "RE879AL1": "10200547328",
            "OP5D2BL1": "14574100480",
            "OP60F5L1": "14952693760",
            "PKX110": "15032385536", # Added for test if needed, usually falls to default
        }
        
        return sizes.get(device_code, default_size)

    def _is_ab_device(self):
        # Check vendor/build.prop for ro.build.ab_update
        prop_file = self.target_dir / "vendor/build.prop"
        if not prop_file.exists():
            return False # Default to A-only if unknown? Or check baserom?
            
        try:
            with open(prop_file, 'r', errors='ignore') as f:
                for line in f:
                    if "ro.build.ab_update=true" in line:
                        return True
        except:
            pass
        return False
