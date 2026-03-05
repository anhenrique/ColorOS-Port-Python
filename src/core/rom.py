import logging
import shutil
import zipfile
import tarfile
import concurrent.futures
import os
from enum import Enum, auto
from pathlib import Path
from src.utils.shell import ShellRunner
from src.utils.imgextractor.imgextractor import Extractor

ANDROID_LOGICAL_PARTITIONS = [
    "system",
    "system_ext",
    "product",
    "vendor",
    "odm",
    "mi_ext",
    "system_dlkm",
    "vendor_dlkm",
    "odm_dlkm",
    "product_dlkm",
]


class RomType(Enum):
    UNKNOWN = auto()
    PAYLOAD = auto()  # payload.bin
    BROTLI = auto()  # new.dat.br
    FASTBOOT = auto()  # super.img or tgz
    LOCAL_DIR = auto()  # Pre-extracted directory


class RomPackage:
    def __init__(self, file_path: str | Path, work_dir: str | Path, label: str = "Rom"):
        self.props = {}
        self.prop_history = {}  # Tracks property history: {key: [(file, value), ...]}
        self.path = Path(file_path).resolve()
        self.work_dir = Path(work_dir).resolve()
        self.label = label
        self.logger = logging.getLogger(label)
        self.shell = ShellRunner()

        # Directory structure definition
        self.images_dir = self.work_dir / "images"  # Stores .img files
        self.extracted_dir = (
            self.work_dir / "extracted"
        )  # Stores extracted folders (system, vendor...)
        self.config_dir = (
            self.work_dir / "extracted" / "config"
        )  # Stores fs_config and file_contexts

        self.rom_type = RomType.UNKNOWN
        self.props = {}

        self._detect_type()

    def _detect_type(self):
        """Detects ROM type (Zip, Payload, or Local Directory)"""
        if not self.path.exists():
            raise FileNotFoundError(f"Path not found: {self.path}")

        if self.path.is_dir():
            self.rom_type = RomType.LOCAL_DIR
            self.logger.info(f"[{self.label}] Source is a local directory.")
            # If in directory mode, assume it's the working directory
            self.work_dir = self.path
            self.images_dir = self.path / "images"  # Adapting to AOSP structure
            if not self.images_dir.exists():
                self.images_dir = self.path  # Compatible if img is in root
            return

        # Simple Zip detection logic
        if zipfile.is_zipfile(self.path):
            with zipfile.ZipFile(self.path, "r") as z:
                namelist = z.namelist()
                if "payload.bin" in namelist:
                    self.rom_type = RomType.PAYLOAD
                elif any(x.endswith("new.dat.br") for x in namelist):
                    self.rom_type = RomType.BROTLI
                elif "images/super.img" in namelist or "super.img" in namelist:
                    self.rom_type = RomType.FASTBOOT
        elif self.path.suffix == ".tgz":
            self.rom_type = RomType.FASTBOOT

        self.logger.info(f"[{self.label}] Detected Type: {self.rom_type.name}")

    def extract_images(self, partitions: list[str] | None = None):
        """
        Level 1 Extraction: Convert Zip/Payload to Img
        :param partitions:
            - If None (Base ROM): Extract ALL imgs from payload.bin (including firmware),
              but only automatically extract (Level 2) ANDROID_LOGICAL_PARTITIONS.
            - If list specified (Port ROM): Extract only specific imgs, and extract them.
        """
        if self.rom_type == RomType.LOCAL_DIR:
            self.logger.info(
                f"[{self.label}] Local dir mode, skipping payload extraction."
            )
            # Local mode, try extracting logical partitions
            self._batch_extract_files(partitions or ANDROID_LOGICAL_PARTITIONS)
            return

        self.images_dir.mkdir(parents=True, exist_ok=True)

        # === Step 1: Payload/Zip -> Images (Extract img) ===
        try:
            if self.rom_type == RomType.PAYLOAD:
                cmd = ["payload-dumper", "--out", str(self.images_dir)]

                if partitions:
                    # Port ROM mode: Extract specific images (e.g., system, product)
                    self.logger.info(
                        f"[{self.label}] Extracting specific images: {partitions} ..."
                    )
                    cmd.extend(["--partitions", ",".join(partitions)])
                else:
                    # Base ROM mode: Extract all images (includes firmware like xbl, boot)
                    self.logger.info(
                        f"[{self.label}] Extracting ALL images (Firmware + Logical) ..."
                    )

                cmd.append(str(self.path))

                # Simple check: If target images seem to exist, skip payload-dumper
                # (Note: Hard to verify if all firmware exists, doing a simple check)
                if not any(self.images_dir.iterdir()):
                    self.shell.run(cmd)
                else:
                    self.logger.info(
                        f"[{self.label}] Images directory not empty, assuming extracted."
                    )

            elif self.rom_type == RomType.BROTLI:
                # 1. Extract zip content
                with zipfile.ZipFile(self.path, "r") as z:
                    for f in z.namelist():
                        should_extract = False

                        # .img handling
                        if f.endswith(".img"):
                            part_name = Path(f).stem
                            if not partitions or part_name in partitions:
                                should_extract = True

                        # .br handling
                        elif f.endswith(".new.dat.br") or f.endswith(".transfer.list"):
                            # Extract partition name from file name (e.g. system.new.dat.br -> system)
                            part_name = Path(f).name.split(".")[0]
                            if not partitions or part_name in partitions:
                                should_extract = True

                        if should_extract:
                            self.logger.info(f"Extracting {f}...")
                            z.extract(f, self.images_dir)

                # 1.5 Fix filenames with numeric suffixes (e.g., system.1.new.dat.br -> system.new.dat.br)
                self._fix_br_filenames()

                # 2. Process .br files
                # Note: We iterate over extracted files in images_dir
                for br_file in self.images_dir.glob("*.new.dat.br"):
                    prefix = br_file.name.replace(".new.dat.br", "")

                    new_dat = self.images_dir / f"{prefix}.new.dat"
                    transfer_list = self.images_dir / f"{prefix}.transfer.list"
                    output_img = self.images_dir / f"{prefix}.img"

                    if output_img.exists():
                        self.logger.info(
                            f"[{self.label}] Image {output_img.name} already exists."
                        )
                        continue

                    if not transfer_list.exists():
                        self.logger.warning(
                            f"Transfer list for {prefix} not found, skipping conversion."
                        )
                        continue

                    # 3. Brotli Decompress
                    self.logger.info(f"[{self.label}] Decompressing {br_file.name}...")
                    try:
                        # brotli -d -f input -o output
                        # We use full path for safety
                        cmd = ["brotli", "-d", "-f", str(br_file), "-o", str(new_dat)]
                        self.shell.run(cmd)
                    except Exception as e:
                        self.logger.error(
                            f"Brotli decompression failed for {prefix}: {e}"
                        )
                        continue

                    # 4. sdat2img
                    self.logger.info(
                        f"[{self.label}] Converting {prefix} to raw image..."
                    )
                    try:
                        # Import here to avoid circular dependencies if any
                        from src.utils.sdat2img import run_sdat2img

                        # sdat2img expects string paths
                        success = run_sdat2img(
                            str(transfer_list), str(new_dat), str(output_img)
                        )

                        if not success:
                            self.logger.error(f"sdat2img failed for {prefix}")
                        else:
                            self.logger.info(
                                f"[{self.label}] Generated {output_img.name}"
                            )

                            # Clean up intermediate files only on success
                            if new_dat.exists():
                                os.remove(new_dat)
                            # Keep original br file? Maybe not if space is concern.
                            # But extract_images usually keeps source images.
                            # Let's delete new.dat but keep br? Or delete br too since it's extracted copy.
                            if br_file.exists():
                                os.remove(br_file)
                            if transfer_list.exists():
                                os.remove(transfer_list)

                    except Exception as e:
                        self.logger.error(f"sdat2img execution failed: {e}")

            elif self.rom_type == RomType.FASTBOOT:
                # Zip mode logic
                has_super = False
                super_path_in_zip = None

                with zipfile.ZipFile(self.path, "r") as z:
                    # 1. First pass: Check for super.img and extract other images
                    for f in z.namelist():
                        if f.endswith("super.img") or f.endswith("images/super.img"):
                            has_super = True
                            super_path_in_zip = f
                            continue

                        if not f.endswith(".img"):
                            continue

                        part_name = Path(f).stem
                        # Skip if it's likely a logical partition inside super (unless explicit .img exists outside)
                        # Actually standard fastboot zips have boot.img, dtbo.img outside super.
                        # Logical partitions (system, vendor) are inside super.

                        # If partitions specified, extract only those; otherwise extract all
                        if partitions and part_name not in partitions:
                            # If it's a firmware image (not logical), we generally want it for Base ROM
                            # But if partitions IS set (Port ROM), we strictly follow it.
                            # Wait, Port ROM extraction calls extract_images(port_partitions).
                            # So we only want system/product etc.
                            # These are likely inside super.img.
                            # So we shouldn't extract boot.img etc if not requested.
                            continue

                        self.logger.info(f"Extracting {f}...")
                        # Flatten structure: Extract file to images_dir directly
                        source = z.open(f)
                        target = open(self.images_dir / Path(f).name, "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)

                    # === Step 1.5: Process Sparse/Split Images (super.img, cust.img) ===
                    self._process_sparse_images()

                    # 2. Handle super.img unpacking
                    super_img = self.images_dir / "super.img"
                    if super_img.exists():
                        self.logger.info(
                            f"[{self.label}] Found super.img, unpacking logical partitions..."
                        )

                        try:
                            # lpunpack is required
                            unpack_cmd = ["lpunpack"]

                            if partitions:
                                self.logger.info(
                                    f"[{self.label}] Unpacking specific partitions: {partitions}"
                                )

                                for part in partitions:
                                    # Try extracting 'part'
                                    cmd = [
                                        "lpunpack",
                                        "-p",
                                        part,
                                        str(super_img),
                                        str(self.images_dir),
                                    ]
                                    try:
                                        self.shell.run(cmd, check=False)
                                    except:
                                        pass

                                    # Try extracting 'part_a' (V-AB)
                                    cmd_a = [
                                        "lpunpack",
                                        "-p",
                                        f"{part}_a",
                                        str(super_img),
                                        str(self.images_dir),
                                    ]
                                    try:
                                        self.shell.run(cmd_a, check=False)
                                    except:
                                        pass

                            else:
                                # Unpack ALL
                                self.logger.info(
                                    f"[{self.label}] Unpacking ALL partitions from super.img..."
                                )
                                self.shell.run(
                                    ["lpunpack", str(super_img), str(self.images_dir)]
                                )

                        except Exception as e:
                            self.logger.error(f"Failed to unpack super.img: {e}")
                            raise
                        finally:
                            # Cleanup super.img to save space?
                            # If Base ROM, we might want to keep it?
                            # Usually we extract logical partitions and use them. super.img is redundant.
                            if super_img.exists():
                                os.remove(super_img)

        except Exception as e:
            self.logger.error(f"Image extraction failed: {e}")
            raise

    def _process_sparse_images(self):
        """
        Merge/Convert sparse images (super.img.*, cust.img.*) to raw images using simg2img
        """
        # Define the binary path (assuming Linux x86_64 for now as per env)
        # In a real scenario, this should be passed from Context or detected properly
        simg2img_bin = Path("bin/linux/x86_64/simg2img").resolve()
        if not simg2img_bin.exists():
            # Fallback to system path
            simg2img_bin = "simg2img"

        # 1. Handle super.img
        super_chunks = sorted(list(self.images_dir.glob("super.img.*")))
        # Filter strictly for numeric suffixes or standard split patterns if needed,
        # but glob "super.img.*" matches the shell script logic.

        target_super = self.images_dir / "super.img"

        if super_chunks:
            self.logger.info(
                f"[{self.label}] Merging sparse super images: {[c.name for c in super_chunks]}..."
            )
            try:
                cmd = (
                    [str(simg2img_bin)]
                    + [str(c) for c in super_chunks]
                    + [str(target_super)]
                )
                self.shell.run(cmd)

                # Cleanup chunks
                for c in super_chunks:
                    os.unlink(c)
            except Exception as e:
                self.logger.error(f"Failed to merge super.img: {e}")
                raise

        elif target_super.exists():
            # Try converting single sparse to raw (in-place replacement strategy)
            # simg2img input output
            self.logger.info(
                f"[{self.label}] converting super.img to raw (if sparse)..."
            )
            temp_raw = self.images_dir / "super.raw.img"
            try:
                self.shell.run([str(simg2img_bin), str(target_super), str(temp_raw)])
                shutil.move(temp_raw, target_super)
            except Exception as e:
                self.logger.warning(
                    f"simg2img conversion skipped/failed (likely already raw): {e}"
                )
                if temp_raw.exists():
                    os.unlink(temp_raw)

        # 2. Handle cust.img
        cust_chunks = sorted(list(self.images_dir.glob("cust.img.*")))
        target_cust = self.images_dir / "cust.img"

        if cust_chunks:
            self.logger.info(f"[{self.label}] Merging sparse cust images...")
            try:
                cmd = (
                    [str(simg2img_bin)]
                    + [str(c) for c in cust_chunks]
                    + [str(target_cust)]
                )
                self.shell.run(cmd)
                for c in cust_chunks:
                    os.unlink(c)
            except Exception as e:
                self.logger.error(f"Failed to merge cust.img: {e}")

    def _fix_br_filenames(self):
        """
        Fix filenames with numeric suffixes in extracted BR files.
        E.g., system.1.new.dat.br -> system.new.dat.br
        This matches the shell script behavior.
        """
        import re

        for file_path in self.images_dir.iterdir():
            if not file_path.is_file():
                continue

            filename = file_path.name
            name, ext = file_path.stem, file_path.suffix

            # Check if filename contains digits that need to be cleaned
            # Pattern: remove digits before known extensions
            if re.search(r"\d", name):
                # Remove digits from the name part (before extensions)
                # E.g., "system.1.new.dat" -> "system.new.dat"
                # The shell script uses: sed 's/[0-9]\+\(\.[^0-9]\+\)/\1/g'
                new_name = re.sub(r"\d+(\.[^\d.]+)", r"\1", name)
                # Clean up double dots
                new_name = new_name.replace("..", ".")

                if new_name != name:
                    new_file_path = self.images_dir / f"{new_name}{ext}"
                    if new_file_path != file_path:
                        self.logger.info(f"Renaming {filename} -> {new_file_path.name}")
                        shutil.move(str(file_path), str(new_file_path))

    def _batch_extract_files(self, candidates: list[str]):
        """
        Batch call extract_partition_to_file (Parallel optimization)
        Automatically checks if img exists, skips if not (e.g., Base ROM might not have mi_ext)
        """
        self.logger.info(
            f"[{self.label}] Processing file extraction for logical partitions..."
        )

        # Dynamic worker count based on CPU cores and partition count
        cpu_count = os.cpu_count() or 4
        partition_count = len(candidates)
        # Use fewer workers for I/O bound tasks to avoid contention
        max_workers = min(cpu_count // 2 + 1, partition_count, 6)

        self.logger.debug(
            f"[{self.label}] Using {max_workers} workers for extraction (CPU: {cpu_count}, Partitions: {partition_count})"
        )

        # Pre-filter valid partitions to avoid unnecessary thread overhead
        valid_partitions = []
        for part in candidates:
            img_path = self.images_dir / f"{part}.img"
            if not img_path.exists():
                img_path = self.images_dir / f"{part}_a.img"

            if img_path.exists():
                # Check if already extracted (cache hit)
                target_dir = self.extracted_dir / part
                config_exists = (self.config_dir / f"{part}_fs_config").exists()
                has_content = target_dir.exists() and any(target_dir.iterdir())

                if has_content and config_exists:
                    self.logger.debug(
                        f"[{self.label}] Partition {part} already extracted, skipping"
                    )
                else:
                    valid_partitions.append(part)
            else:
                self.logger.debug(
                    f"[{self.label}] Partition image {part} not found, skipping extract."
                )

        if not valid_partitions:
            self.logger.info(
                f"[{self.label}] All partitions already extracted, skipping extraction"
            )
            return

        # Use ThreadPoolExecutor for parallel extraction with progress tracking
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks with partition names for better error reporting
            future_to_part = {
                executor.submit(self.extract_partition_to_file, part): part
                for part in valid_partitions
            }

            completed = 0
            total = len(valid_partitions)

            for future in concurrent.futures.as_completed(future_to_part):
                part = future_to_part[future]
                try:
                    future.result()
                    completed += 1
                    if completed % 2 == 0 or completed == total:
                        self.logger.info(
                            f"[{self.label}] Extraction progress: {completed}/{total} partitions"
                        )
                except Exception as e:
                    self.logger.error(
                        f"[{self.label}] Partition extraction failed for {part}: {e}"
                    )
                    raise

        self.logger.info(
            f"[{self.label}] Extraction completed: {completed}/{total} partitions"
        )

    def extract_partition_to_file(self, part_name: str) -> Path | None:
        """
        Level 2 Extraction: Extract Img to folder, preserving SELinux config
        :return: Path to extracted folder (e.g., build/stock/extracted/)
        """
        target_dir = self.extracted_dir / part_name

        # === Modification: Stricter cache check ===
        # Check if dir has content AND fs_config exists to consider it "extracted"
        # Otherwise consider incomplete, re-extract
        config_exists = (self.config_dir / f"{part_name}_fs_config").exists()
        has_content = target_dir.exists() and any(target_dir.iterdir())

        if has_content and config_exists:
            self.logger.info(
                f"[{self.label}] Partition {part_name} already extracted (verified)."
            )
            return target_dir

        # 2. Check if img exists
        img_path = self.images_dir / f"{part_name}.img"
        if not img_path.exists():
            # Try finding _a.img (for V-AB)
            img_path = self.images_dir / f"{part_name}_a.img"
            if not img_path.exists():
                self.logger.warning(f"[{self.label}] Image {part_name}.img not found.")
                return None

        self.logger.info(f"[{self.label}] Extracting {part_name}.img to filesystem...")
        target_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 3. Detect filesystem type
        fs_type = self._detect_filesystem(img_path)
        self.logger.info(
            f"[{self.label}] Detected filesystem for {part_name}: {fs_type}"
        )

        if fs_type == "sparse_image":
            self.logger.info(
                f"[{self.label}] {part_name}.img is sparse, converting to raw..."
            )
            # We already have simg2img detection in _process_sparse_images,
            # but let's do a quick local conversion if needed.
            # Usually images from lpunpack are already raw.
            # But if somehow it's still sparse:
            try:
                from src.utils.imgextractor.imgextractor import simg2img

                simg2img(str(img_path))
                fs_type = self._detect_filesystem(img_path)
            except Exception as e:
                self.logger.warning(f"Sparse conversion failed: {e}")

        # 4. Extract based on filesystem
        if fs_type == "erofs":
            try:
                cmd = [
                    "extract.erofs",
                    "-x",
                    "-i",
                    str(img_path),
                    "-o",
                    str(self.extracted_dir),
                ]
                self.shell.run(cmd, capture_output=True)
            except Exception as e:
                self.logger.error(f"EROFS extraction failed: {e}")
                # Fallback to 7z if erofs extraction tool fails unexpectedly
                try:
                    import subprocess

                    cmd = ["7z", "x", str(img_path), f"-o{self.extracted_dir}", "-y"]
                    subprocess.run(cmd, check=True)
                except:
                    return None
        elif fs_type == "ext4":
            try:
                self.logger.info(
                    f"[{self.label}] Using Extractor for ext4 partition {part_name}"
                )
                extractor = Extractor()
                # Extractor.main handles both extraction and config generation
                extractor.main(str(img_path), str(target_dir))
            except Exception as e:
                self.logger.error(f"EXT4 extraction failed via Extractor: {e}")
                # Fallback to 7z
                try:
                    import subprocess

                    cmd = ["7z", "x", str(img_path), f"-o{self.extracted_dir}", "-y"]
                    subprocess.run(cmd, check=True)
                except:
                    return None
        else:
            # Unknown filesystem, try 7z as last resort
            self.logger.warning(
                f"[{self.label}] Unknown filesystem {fs_type} for {part_name}, trying 7z"
            )
            try:
                import subprocess

                cmd = ["7z", "x", str(img_path), f"-o{self.extracted_dir}", "-y"]
                subprocess.run(cmd, check=True)
            except Exception as e:
                self.logger.error(
                    f"Final extraction attempt failed for {part_name}: {e}"
                )
                return None

        # 5. [Critical] Process config files (fs_config / file_contexts)
        # Move generated config files to self.config_dir if they were not already placed there
        # Extractor.main already places them in self.config_dir (which is its self.CONFING_DIR)

        # Find potentially generated context files
        possible_contexts = list(
            target_dir.parent.glob(f"{part_name}*_file_contexts")
        ) + list(target_dir.glob("*_file_contexts"))

        possible_fs_config = list(
            target_dir.parent.glob(f"{part_name}*_fs_config")
        ) + list(target_dir.glob("*_fs_config"))

        for src in possible_contexts:
            dst = self.config_dir / f"{part_name}_file_contexts"
            if src.resolve() != dst.resolve():
                if dst.exists():
                    dst.unlink()
                shutil.move(src, dst)
                self.logger.debug(f"Saved file_contexts for {part_name}")
                break

        for src in possible_fs_config:
            dst = self.config_dir / f"{part_name}_fs_config"
            if src.resolve() != dst.resolve():
                if dst.exists():
                    dst.unlink()
                shutil.move(src, dst)
                self.logger.debug(f"Saved fs_config for {part_name}")
                break

        return target_dir

    def get_config_files(self, part_name):
        """Get config file paths for a partition"""
        return (
            self.config_dir / f"{part_name}_fs_config",
            self.config_dir / f"{part_name}_file_contexts",
        )

    def _detect_filesystem(self, img_path: Path) -> str:
        """Detect filesystem type by reading magic bytes at standard offsets"""
        try:
            with open(img_path, "rb") as f:
                header = f.read(4096)

            if len(header) < 2048:
                self.logger.warning(f"File too small to detect filesystem: {img_path}")
                return "unknown"

            if header[0x400:0x404] == bytes([0xE2, 0xE1, 0xF5, 0xE0]):
                return "erofs"

            if header[0x438:0x43A] == bytes([0x53, 0xEF]):
                return "ext4"

            if header[0x400:0x404] == bytes([0x10, 0x20, 0xF5, 0xF2]):
                return "f2fs"

            if header[0:4] == bytes([0x3A, 0xFF, 0x26, 0xED]):
                return "sparse_image"

            return "unknown"

        except Exception as e:
            self.logger.warning(f"Failed to detect filesystem for {img_path}: {e}")
            return "unknown"

    def parse_all_props(self):
        """
        [Optimization] Find all build.prop files in known partition locations
        Avoids slow rglob through thousands of app/lib directories.
        """
        if not self.extracted_dir.exists():
            self.logger.warning(
                f"[{self.label}] Extracted dir not found, skipping props parsing."
            )
            return

        self.props = {}
        self.prop_history = {}

        self.logger.info(f"[{self.label}] Scanning and parsing build.prop files...")

        # 1. Define known locations for build.prop
        # Structure: <partition>/build.prop or <partition>/etc/build.prop
        partitions = [
            "system/system",
            "system",
            "vendor",
            "product",
            "odm",
            "system_ext",
            "my_product",
            "my_manifest",
            "my_stock",
            "my_region",
            "my_carrier",
            "mi_ext",
        ]

        prop_files = []
        for part in partitions:
            # Check partition root
            p1 = self.extracted_dir / part / "build.prop"
            if p1.exists():
                prop_files.append(p1)

            # Check etc directory
            p2 = self.extracted_dir / part / "etc" / "build.prop"
            if p2.exists():
                prop_files.append(p2)

        if not prop_files:
            # Fallback only if no standard props found
            self.logger.debug(
                f"[{self.label}] No standard build.prop found, falling back to limited scan."
            )
            prop_files = list(self.extracted_dir.glob("*/build.prop")) + list(
                self.extracted_dir.glob("*/etc/build.prop")
            )

        # 2. Sort (System -> Vendor -> ... -> my_product -> my_manifest)
        # Higher index means parsed LATER and thus has HIGHER priority (overwrites previous)
        def sort_priority(path):
            p = str(path).lower()
            if "system/system" in p:
                return 0
            if "system/" in p:
                return 1
            if "vendor" in p:
                return 2
            if "product" in p:
                return 3
            if "odm" in p:
                return 4
            if "my_product" in p:
                return 10
            if "my_manifest" in p:
                return 11
            return 50

        # Remove duplicates while preserving order (using dict)
        prop_files = list(dict.fromkeys(prop_files))
        prop_files.sort(key=sort_priority)

        # 3. Parse one by one
        for prop_file in prop_files:
            self._load_single_prop_file(prop_file)

        self.logger.info(
            f"[{self.label}] Loaded {len(self.props)} properties from {len(prop_files)} files."
        )

    def _load_single_prop_file(self, file_path: Path):
        """Helper: Parse single file and update self.props"""
        # Calculate relative path for display (e.g. system/build.prop)
        try:
            rel_path = file_path.relative_to(self.extracted_dir)
        except ValueError:
            rel_path = file_path.name  # Fallback

        self.logger.debug(f"Parsing: {rel_path}")

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
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
            self.logger.error(f"Error reading {rel_path}: {e}")

    def export_props(self, output_path: str | Path):
        """
        [New] Export all props to file, including Override debug info
        """
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"[{self.label}] Exporting debug props to {out_file} ...")

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

        with open(out_file, "w", encoding="utf-8") as f:
            f.write("\n".join(content))

        self.logger.info(f"[{self.label}] Debug props saved.")

    def get_prop(self, key: str, default: str | None = None) -> str | None:
        """
        Get property value.
        Triggers full load if cache is empty.
        """
        if not self.props:
            self.parse_all_props()
        return self.props.get(key, default)

    def scan_apks(self) -> dict:
        """
        Scan all APK files in extracted directory and extract metadata.
        Returns dict: {package_name: {'path': Path, 'version_code': int, 'version_name': str}}
        """
        if hasattr(self, "_apk_cache") and self._apk_cache:
            return self._apk_cache

        self._apk_cache = {}
        self.logger.info(f"[{self.label}] Scanning APKs...")

        if not self.extracted_dir.exists():
            return self._apk_cache

        apk_files = list(self.extracted_dir.rglob("*.apk"))

        def _parse_apk(apk):
            try:
                # Use self.shell.run to handle binary pathing and LD_LIBRARY_PATH
                # Use aapt2 as it is more modern and available in the project
                # Set silent=True to avoid flooding debug log with every APK command
                result = self.shell.run(
                    ["aapt2", "dump", "badging", str(apk)],
                    capture_output=True,
                    check=False,
                    silent=True,
                )

                if result.returncode != 0:
                    return None, None

                output = result.stdout

                package_name = None
                version_code = None
                version_name = None

                for line in output.split("\n"):
                    if line.startswith("package: name='"):
                        # Format: package: name='com.foo' versionCode='123' versionName='1.0' ...
                        pkg = line.split("name='")[1].split("'")[0]
                        package_name = pkg

                        if "versionCode='" in line:
                            vc = line.split("versionCode='")[1].split("'")[0]
                            version_code = int(vc) if vc.isdigit() else None

                        if "versionName='" in line:
                            version_name = line.split("versionName='")[1].split("'")[0]
                        break  # Optimization: package info is usually on first line

                if package_name:
                    return package_name, {
                        "path": apk,
                        "relative_path": apk.relative_to(self.extracted_dir),
                        "version_code": version_code,
                        "version_name": version_name,
                    }
            except Exception as e:
                self.logger.debug(f"Failed to parse {apk.name}: {e}")
            return None, None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=os.cpu_count() or 4
        ) as executor:
            results = executor.map(_parse_apk, apk_files)

            for pkg_name, info in results:
                if pkg_name:
                    self._apk_cache[pkg_name] = info

        self.logger.info(f"[{self.label}] Found {len(self._apk_cache)} APKs")

        # Save results to file for manual inspection/debugging
        self._save_apk_scan_results()

        return self._apk_cache

    def _save_apk_scan_results(self):
        """Save APK scan cache to a JSON file for user inspection"""
        import json

        if not self._apk_cache:
            return

        # Save to build directory instead of extracted config
        project_root = Path(__file__).resolve().parent.parent.parent
        output_dir = project_root / "build"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"apk_scan_{self.label.lower()}.json"

        serializable = {}
        # Path objects are not JSON serializable, convert to strings
        for pkg, info in sorted(self._apk_cache.items()):
            serializable[pkg] = {
                "path": str(info["path"]),
                "relative_path": str(info["relative_path"]),
                "version_code": info["version_code"],
                "version_name": info["version_name"],
            }

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=4, ensure_ascii=False)
            self.logger.info(f"[{self.label}] APK scan results saved to: {output_file}")
        except Exception as e:
            self.logger.warning(f"[{self.label}] Failed to save APK scan results: {e}")

    def _find_aapt(self) -> Path:
        """Find aapt binary in bin directory (Deprecated: use self.shell.run)"""
        return Path("aapt")
