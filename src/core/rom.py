import shutil
import logging
import zipfile
import os
import fnmatch
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
        self.props = {}
        self.prop_history = {}


    def extract(self, tools: ToolManager, partitions: list[str] | None = None):
        logger.info(f"Extracting {self.label} ROM from {self.path}...")
        
        # Check if already extracted (simple check)
        if self.images_dir.exists() and any(self.images_dir.iterdir()):
             logger.info(f"Images directory {self.images_dir} already exists and is not empty. Skipping extraction.")
             return

        if self.extracted_dir.exists():
            shutil.rmtree(self.extracted_dir)
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Identify ROM Type
        if self.path.suffix == ".zip":
            if self._check_file_in_zip("payload.bin"):
                self.rom_type = "payload"
                self._extract_payload_zip(tools, partitions)
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
             self._extract_payload_bin(tools, partitions)
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

    def _extract_payload_zip(self, tools: ToolManager, partitions: list[str] | None = None):
        logger.info(f"Detected payload.bin in zip {self.path.name}.")
        # Use payload-dumper directly on the zip file, avoiding extraction overhead
        self._extract_payload_bin_file(self.path, tools, partitions)

    def _extract_payload_bin(self, tools: ToolManager, partitions: list[str] | None = None):
         self._extract_payload_bin_file(self.path, tools, partitions)

    def _extract_payload_bin_file(self, payload_path, tools: ToolManager, partitions: list[str] | None = None):
        logger.info("Running payload-dumper...")
        tool = tools.get_tool("payload-dumper")
        
        # specific logic for portrom: if partitions are provided, check if we need to expand wildcards
        # or if we are in "portrom" mode (implied by usage, but here we just handle the provided list)
        # However, the user request says "portrom ONLY extracts system, product, system_ext and my_*".
        # This implies we should probably do this filtering HERE if it's the PortROM, 
        # OR the caller should provide the list. 
        # Since I am editing rom.py, let's make it smart.
        
        try:
            # First, if partitions is NOT None, we use it. 
            # If it contains wildcards (e.g. "my_*"), we need to query the payload first.
            
            final_partitions = []
            if partitions:
                # Check for wildcards
                has_wildcard = any("*" in p for p in partitions)
                
                if has_wildcard:
                    logger.info("Wildcards found in partition list. Listing payload content...")
                    # Run list command
                    # payload-dumper --list payload.bin
                    list_cmd = f"{tool} --list {payload_path}"
                    output = Shell.run(list_cmd)
                    
                    logger.info(f"Payload content raw output:\n{output}")  # DEBUG LOG

                    available_partitions = []
                    # Handle output: "system(934.9MB), system_ext(823.0MB), product(8.8MB), ..."
                    # First, we need to handle multi-line or single-line output.
                    # The sample output suggests it might be all on one line or split.
                    # Let's join all lines into one string, then split by comma.
                    full_output = " ".join(output.splitlines())
                    
                    # Split by comma
                    raw_parts = full_output.split(',')
                    
                    for raw_part in raw_parts:
                        raw_part = raw_part.strip()
                        if not raw_part: continue
                        
                        # Format is "name(size)" or just "name"
                        if '(' in raw_part:
                            p_name = raw_part.split('(')[0].strip()
                        else:
                            # If no parens, it might be just "system" or "system 100MB" or whatever
                            # Safe bet: split by space and take first token
                            # But wait, what if raw_part is "system" -> p_name="system"
                            # What if raw_part is "system_ext" -> p_name="system_ext"
                            # If raw_part was split by comma from "system(1MB), system_ext(2MB)"
                            # Then raw_part is " system_ext(2MB)" -> stripped "system_ext(2MB)"
                            p_split = raw_part.split()
                            if p_split:
                                p_name = p_split[0].strip()
                            else:
                                continue

                        if p_name and not p_name.startswith("-") and ":" not in p_name and not p_name.lower().startswith("payload"):
                            available_partitions.append(p_name)
                    
                    logger.info(f"Parsed available partitions: {available_partitions}") 

                    import fnmatch
                    
                    # Pre-process available partitions to strip _a/_b suffix for matching if needed?
                    # Or just match against full names.
                    
                    for req_part in partitions:
                        if "*" in req_part:
                            # Match wildcard against FULL available names (e.g. my_stock_a)
                            matches = fnmatch.filter(available_partitions, req_part)
                            if matches:
                                final_partitions.extend(matches)
                            else:
                                # Try matching with _a suffix if wildcard didn't match anything?
                                # e.g. req="my_*" -> available="my_stock_a" -> match?
                                # "my_*" matches "my_stock_a". So this is fine.
                                logger.warning(f"Wildcard '{req_part}' matched nothing.")
                        else:
                            # Direct match
                            if req_part in available_partitions:
                                final_partitions.append(req_part)
                            # Handle A/B partition suffix automatically
                            elif f"{req_part}_a" in available_partitions:
                                final_partitions.append(f"{req_part}_a")
                                logger.info(f"Auto-selected {req_part}_a for {req_part}")
                            elif f"{req_part}_b" in available_partitions:
                                final_partitions.append(f"{req_part}_b")
                                logger.info(f"Auto-selected {req_part}_b for {req_part}")
                            else:
                                logger.warning(f"Partition {req_part} not found in payload.")
                    
                    # Deduplicate
                    final_partitions = sorted(list(set(final_partitions)))
                    logger.info(f"Resolved partitions: {final_partitions}")
                else:
                    final_partitions = partitions

            cmd = f"{tool} --out {self.images_dir}"
            if final_partitions:
                logger.info(f"Extracting specific images: {final_partitions} ...")
                cmd += f" --partitions {','.join(final_partitions)}"
            elif partitions is not None and len(final_partitions) == 0:
                 logger.warning("No partitions matched the criteria. Extracting nothing.")
                 return # Nothing to do
            else:
                logger.info("Extracting ALL images ...")
            
            try:
                import multiprocessing
                cpu_count = multiprocessing.cpu_count()
            except:
                cpu_count = 4
            
            # Use max workers
            cmd += f" --workers {cpu_count}"
            cmd += f" {payload_path}"
            
            # Use Shell.run without capturing output to stream to console
            Shell.run(cmd, capture_output=False)
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

    def extract_partition_to_file(self, part_name: str, tools: ToolManager) -> Path | None:
        """
        Extract partition to internal extracted directory (Level 2 Extraction).
        Returns the path to the extracted directory.
        """
        # Define internal extraction path - use parent dir to avoid double nesting
        # extract.erofs creates a subdirectory with partition name
        target_dir = self.extracted_dir
        
        # Check if already extracted (check for marker or non-empty dir)
        config_exists = (self.work_dir / "config" / f"{part_name}_fs_config").exists()
        extracted_part_dir = target_dir / part_name
        if extracted_part_dir.exists() and any(extracted_part_dir.iterdir()) and config_exists:
             logger.info(f"[{self.label}] Partition {part_name} already extracted.")
             return extracted_part_dir
              
        # Not extracted, so do it.
        img_path = self.images_dir / f"{part_name}.img"
        if not img_path.exists():
            # Try _a
            img_path = self.images_dir / f"{part_name}_a.img"
            if not img_path.exists():
                logger.warning(f"[{self.label}] Image {part_name}.img not found.")
                return None

        logger.info(f"[{self.label}] Extracting {part_name}.img to {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        fs_type = self._detect_fs_type(img_path)
        
        try:
            if fs_type == "erofs":
                tool = tools.get_tool("extract.erofs")
                Shell.run(f"{tool} -i {img_path} -x -o {target_dir}")
                
            elif fs_type == "ext4":
                 Shell.run(f"7z x {img_path} -o{target_dir} -y")
            else:
                 logger.warning(f"Unknown filesystem type for {part_name} in {img_path}")
                 return None
                 
            self._organize_config_files(part_name, target_dir)
            
            img_path.unlink(missing_ok=True)
            logger.info(f"[{self.label}] Deleted {img_path.name} to save space")
            
            return extracted_part_dir
            
        except Exception as e:
            logger.error(f"Failed to extract {part_name}: {e}")
            return None

    def _organize_config_files(self, part_name, target_dir):
        config_dir = self.work_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Check inside target_dir
        fc_candidates = list(target_dir.glob("*file_contexts")) + list(target_dir.glob(f"{part_name}*file_contexts"))
        fs_candidates = list(target_dir.glob("*fs_config")) + list(target_dir.glob(f"{part_name}*fs_config"))

        # 2. Check parent dir (extract.erofs sometimes puts context file in parent of output dir)
        # But here target_dir is the output dir.
        
        if fc_candidates:
            src = fc_candidates[0]
            dst = config_dir / f"{part_name}_file_contexts"
            shutil.move(src, dst)
            logger.debug(f"Moved file_contexts for {part_name}")
            
        if fs_candidates:
            src = fs_candidates[0]
            dst = config_dir / f"{part_name}_fs_config"
            shutil.move(src, dst)
            logger.debug(f"Moved fs_config for {part_name}")

    def get_config_files(self, part_name):
        config_dir = self.work_dir / "config"
        return (
            config_dir / f"{part_name}_fs_config",
            config_dir / f"{part_name}_file_contexts"
        )

    def extract_partition(self, partition_name, target_dir, tools: ToolManager):
        # Deprecated method, redirects to extract_partition_to_file and copies content
        src_dir = self.extract_partition_to_file(partition_name, tools)
        if src_dir and src_dir.exists():
            if target_dir.exists(): shutil.rmtree(target_dir)
            # Use copytree to copy content
            shutil.copytree(src_dir, target_dir, symlinks=True, dirs_exist_ok=True)



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

    def parse_all_props(self):
        """
        [Optimization] Recursively find all build.prop files in extracted dir
        """
        if not self.extracted_dir.exists():
            logger.warning(f"[{self.label}] Extracted dir not found, skipping props parsing.")
            return

        # [New] Clear history to prevent stacking from multiple calls
        self.props = {}
        self.prop_history = {}

        logger.info(f"[{self.label}] Scanning and parsing all build.prop files...")

        # 1. Find files
        prop_files = list(self.extracted_dir.rglob("build.prop"))
        if not prop_files:
            logger.warning(f"[{self.label}] No build.prop files found.")
            return

        # 2. Sort (System -> Vendor -> Product ...)
        def sort_priority(path):
            p = str(path).lower()
            if "system" in p: return 0
            if "vendor" in p: return 1
            if "product" in p: return 2
            if "odm" in p: return 3
            if "mi_ext" in p: return 4
            return 99
        prop_files.sort(key=sort_priority)

        # 3. Parse one by one
        for prop_file in prop_files:
            self._load_single_prop_file(prop_file)
            
        logger.info(f"[{self.label}] Loaded {len(self.props)} properties from {len(prop_files)} files.")

    def _load_single_prop_file(self, file_path: Path):
        """Helper: Parse single file and update self.props"""
        # Calculate relative path for display (e.g. system/build.prop)
        try:
            rel_path = file_path.relative_to(self.extracted_dir)
        except ValueError:
            rel_path = file_path.name # Fallback

        logger.debug(f"Parsing: {rel_path}")

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # [Core Mod] Track history
                    if key not in self.prop_history:
                        self.prop_history[key] = []
                    
                    # Add (source file, value) to history list
                    self.prop_history[key].append((str(rel_path), value))
                    
                    # Update current effective value (Last-win strategy)
                    self.props[key] = value

        except Exception as e:
            logger.error(f"Error reading {rel_path}: {e}")

    def export_props(self, output_path: str | Path):
        """
        [New] Export all props to file, including Override debug info
        """
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"[{self.label}] Exporting debug props to {out_file} ...")
        
        # Ensure loaded
        if not self.props:
            self.parse_all_props()

        content = []
        content.append(f"# DEBUG DUMP for {self.label}")
        content.append(f"# Generated by HyperOS Porting Tool")
        content.append(f"# ==========================================\n")

        # Sort by Key for easy viewing
        for key in sorted(self.props.keys()):
            history = self.prop_history.get(key, [])
            final_val = self.props[key]

            # Check for Override (history > 1 and value changed)
            # Note: Sometimes different files define same value, counts as "override" but value unchanged
            if len(history) > 1:
                content.append(f"# [OVERRIDE DETECTED]")
                content.append(f"# {key}")
                # Print change trajectory
                for source, val in history:
                    content.append(f"#   - {source}: {val}")
                content.append(f"#   -> Final: {final_val}")
            
            # Write actual key-value pair
            content.append(f"{key}={final_val}")
        
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(content))
        
        logger.info(f"[{self.label}] Debug props saved.")

    def get_prop(self, key: str, default: str | None = None) -> str | None:
        """
        Get property value.
        Triggers full load if cache is empty.
        """
        if not self.props:
            self.parse_all_props()
        return self.props.get(key, default)
