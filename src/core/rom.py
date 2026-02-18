import shutil
import logging
import zipfile
import os
from pathlib import Path
from src.utils.shell import Shell
from src.core.tools import ToolManager

logger = logging.getLogger(__name__)

class RomPackage:
    def __init__(self, path: str, work_dir: Path, label: str):
        self.path = Path(path).resolve()
        self.work_dir = work_dir
        self.label = label
        self.extracted_dir = self.work_dir / "extracted"
        self.images_dir = self.extracted_dir / "images"
        self.rom_type = "unknown"

    def extract(self, tools: ToolManager):
        logger.info(f"Extracting {self.label} ROM from {self.path}...")
        
        if self.extracted_dir.exists():
            shutil.rmtree(self.extracted_dir)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Identify ROM Type
        if self.path.suffix == ".zip":
            if self._check_file_in_zip("payload.bin"):
                self.rom_type = "payload"
                self._extract_payload_zip(tools)
            elif self._check_file_in_zip("system.new.dat.br") or self._check_file_in_zip("system.new.dat"):
                self.rom_type = "br"
                self._extract_br_zip(tools)
            elif self._check_file_in_zip_pattern("*.img"):
                self.rom_type = "img"
                self._extract_img_zip()
            else:
                logger.error("Unknown ROM type or invalid zip structure.")
                raise ValueError("Unknown ROM type")
        elif self.path.name == "payload.bin":
             self.rom_type = "payload"
             self._extract_payload_bin(tools)
        else:
            # Assume it's a directory or other format? For now only zip/payload.bin
            logger.error(f"Unsupported file format: {self.path}")
             
        logger.info(f"{self.label} extraction complete. Images in {self.images_dir}")

    def _check_file_in_zip(self, filename):
        try:
            with zipfile.ZipFile(self.path, 'r') as z:
                return filename in z.namelist()
        except zipfile.BadZipFile:
            return False

    def _check_file_in_zip_pattern(self, pattern):
        try:
            with zipfile.ZipFile(self.path, 'r') as z:
                import fnmatch
                return any(fnmatch.fnmatch(name, pattern) for name in z.namelist())
        except zipfile.BadZipFile:
            return False

    def _extract_payload_zip(self, tools: ToolManager):
        logger.info("Detected payload.bin in zip. Extracting...")
        # Extract payload.bin first
        temp_payload = self.work_dir / "payload.bin"
        
        with zipfile.ZipFile(self.path, 'r') as z:
            # Optimize: Stream extraction instead of read() into memory
            with z.open("payload.bin") as source, open(temp_payload, "wb") as target:
                shutil.copyfileobj(source, target)
        
        self._extract_payload_bin_file(temp_payload, tools)
        temp_payload.unlink()

    def _extract_payload_bin(self, tools: ToolManager):
         self._extract_payload_bin_file(self.path, tools)

    def _extract_payload_bin_file(self, payload_path, tools: ToolManager):
        # Changed to use payload-dumper (python/binary) instead of payload-dumper-go
        logger.info("Running payload-dumper...")
        tool = tools.get_tool("payload-dumper")
        try:
            # Usage: payload-dumper --out <output_dir> <input_file>
            Shell.run(f"{tool} --out {self.images_dir} {payload_path}")
        except Exception as e:
            logger.error(f"payload-dumper failed: {e}")
            raise e

    def _extract_br_zip(self, tools: ToolManager):
        logger.info("Detected Brotli compressed system. Extracting...")
        with zipfile.ZipFile(self.path, 'r') as z:
            z.extractall(self.extracted_dir)
        
        for br_file in self.extracted_dir.glob("*.new.dat.br"):
            logger.info(f"Decompressing {br_file.name}...")
            tool_brotli = tools.get_tool("brotli")
            Shell.run(f"{tool_brotli} -d {br_file}")
            dat_file = br_file.with_suffix("") 
            
            transfer_list = self.extracted_dir / f"{br_file.stem.split('.')[0]}.transfer.list"
            img_file = self.images_dir / f"{br_file.stem.split('.')[0]}.img"
            
            if transfer_list.exists() and dat_file.exists():
                logger.info(f"Converting {dat_file.name} to IMG...")
                tool_sdat = tools.get_tool("sdat2img.py")
                # Ensure python3 is used for .py scripts
                Shell.run(f"python3 {tool_sdat} {transfer_list} {dat_file} {img_file}")
                
                dat_file.unlink()
                transfer_list.unlink()

    def _extract_img_zip(self):
        logger.info("Detected IMG files in zip. Extracting...")
        with zipfile.ZipFile(self.path, 'r') as z:
             for info in z.infolist():
                 if info.filename.endswith(".img"):
                     z.extract(info, self.images_dir)

    def get_prop(self, key):
        pass

    def extract_partition(self, partition_name, target_dir, tools: ToolManager):
        img_path = self.images_dir / f"{partition_name}.img"
        if not img_path.exists():
             logger.warning(f"Image {partition_name}.img not found in {self.images_dir}")
             return

        logger.info(f"Extracting partition {partition_name} to {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        fs_type = self._detect_fs_type(img_path)
        
        if fs_type == "erofs":
            tool = tools.get_tool("extract.erofs")
            # extract.erofs -i <image> -x -o <output_dir>
            # Note: The tool might be strictly named extract.erofs or have arguments
            Shell.run(f"{tool} -i {img_path} -x -o {target_dir}")
            
        elif fs_type == "ext4":
             # Use 7z
             tool = "7z" 
             Shell.run(f"7z x {img_path} -o{target_dir} -y")
        else:
             logger.warning(f"Unknown filesystem type for {partition_name} in {img_path}")

    def _detect_fs_type(self, img_path):
        try:
             output = Shell.run(f"file {img_path}")
             if "EROFS" in output:
                 return "erofs"
             elif "ext4" in output or "Linux" in output: 
                 return "ext4"
        except:
            pass
        return "unknown"
