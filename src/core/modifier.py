import json
import os
import re
import shutil
import logging
import concurrent.futures
import tempfile
import zipfile
import urllib.request
from urllib.error import URLError
from pathlib import Path

from src.utils.shell import ShellRunner
from src.utils.smalikit import SmaliKit, SmaliArgs

# Enhanced config handling imports
from src.core.config_schema import validate_config
from src.core.conditions import ConditionEvaluator, BuildContext
from src.core.config_merger import ConfigMerger, MergeReport


class SystemModifier:
    def __init__(self, context):
        self.ctx = context
        self.logger = logging.getLogger("Modifier")
        self.shell = ShellRunner()

        self.bin_dir = Path("bin").resolve()
        self.apktool = self.bin_dir / "apktool.jar"

        self.temp_dir = self.ctx.target_dir.parent / "temp"

        self._file_cache = {}  # Cache for file path lookups
        self._dir_cache = {}  # Cache for directory path lookups

    def run(self):
        self.logger.info("Starting System Modification...")

        self.temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.android_version = int(
                self.ctx.port.get_prop("ro.build.version.release", "14")
            )
        except:
            self.android_version = 14

        # Order matters!
        self._process_replacements()
        self._apply_override_zips()  # New call for conditional ZIP/file ops

        # Migrate permissions and configs from baserom
        self._migrate_oplus_features_configs()

        # ColorOS specific: Apply XML features from config
        self._apply_coloros_features()

        # Optional: Dolby fix
        self._fix_dolby_audio()

        # Optional: AI Memory / AppBooster
        self._apply_ai_memory()

        self._fix_vndk_apex()
        self._fix_vintf_manifest()

        self.logger.info("System Modification Completed.")

    def _migrate_oplus_features_configs(self):
        """
        Migrates permission and configuration files from baserom to portrom (target_dir).
        Matches the logic from port.sh for my_product and region-specific app_v2.xml edits.
        """
        self.logger.info("Migrating permission and configuration files...")

        target_product_etc = self.ctx.target_dir / "my_product" / "etc"
        stock_product_etc = self.ctx.stock.extracted_dir / "my_product" / "etc"

        if not target_product_etc.exists() or not stock_product_etc.exists():
            self.logger.warning(
                "my_product/etc not found in target or stock, skipping migration."
            )
            return

        # 1. Backup portrom permissions/extensions (currently in target_dir)
        with tempfile.TemporaryDirectory(prefix="perm_backup_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_perms = tmp_path / "permissions"
            tmp_exts = tmp_path / "extension"
            tmp_perms.mkdir()
            tmp_exts.mkdir()

            target_perms = target_product_etc / "permissions"
            target_exts = target_product_etc / "extension"

            if target_perms.exists():
                for f in target_perms.glob("*.xml"):
                    shutil.copy2(f, tmp_perms)

            if target_exts.exists():
                for f in target_exts.glob("*.xml"):
                    shutil.copy2(f, tmp_exts)

            # 2. Copy baserom permissions to target (overwriting)
            stock_perms = stock_product_etc / "permissions"
            if stock_perms.exists():
                target_perms.mkdir(parents=True, exist_ok=True)
                for f in stock_perms.glob("*.xml"):
                    shutil.copy2(f, target_perms)

            # 3. Selectively restore portrom files from backup
            patterns = [
                "multimedia*.xml",
                "*permissions*.xml",
                "*google*.xml",
                "*configs*.xml",
                "*gsm*.xml",
                "feature_activity_preload.xml",
                "*gemini*.xml",
                "*gms*.xml",
            ]

            for pattern in patterns:
                for f in tmp_perms.glob(pattern):
                    shutil.copy2(f, target_perms)
                    self.logger.debug(f"Restored {f.name} from backup")

            # 4. Copy more from baserom
            stock_exts = stock_product_etc / "extension"
            if stock_exts.exists():
                target_exts.mkdir(parents=True, exist_ok=True)
                for f in stock_exts.glob("*.xml"):
                    shutil.copy2(f, target_exts)

            # refresh_rate_config.xml
            refresh_rate = stock_product_etc / "refresh_rate_config.xml"
            if refresh_rate.exists():
                shutil.copy2(
                    refresh_rate, target_product_etc / "refresh_rate_config.xml"
                )

            # sys_resolution_switch_config.xml
            resolution_config = stock_product_etc / "sys_resolution_switch_config.xml"
            if resolution_config.exists():
                shutil.copy2(
                    resolution_config,
                    target_product_etc / "sys_resolution_switch_config.xml",
                )

            # com.oplus.sensor_config.xml
            sensor_config = stock_perms / "com.oplus.sensor_config.xml"
            if sensor_config.exists():
                shutil.copy2(
                    sensor_config, target_perms / "com.oplus.sensor_config.xml"
                )

        # 5. Region-specific app_v2.xml edit
        regionmark = getattr(self.ctx, "base_regionmark", "CN")
        if regionmark != "CN":
            app_v2 = self.ctx.target_dir / "my_stock" / "etc" / "config" / "app_v2.xml"
            if app_v2.exists():
                self.logger.info(
                    f"Applying region-specific fixes to {app_v2} (region: {regionmark})"
                )
                content = app_v2.read_text(encoding="utf-8", errors="ignore")
                pkgs = [
                    "com.android.contacts",
                    "com.android.incallui",
                    "com.android.mms",
                    "com.oplus.blacklistapp",
                    "com.oplus.phonenoareainquire",
                    "com.ted.number",
                ]
                lines = content.splitlines()
                new_lines = []
                for line in lines:
                    should_skip = False
                    for pkg in pkgs:
                        if pkg in line:
                            should_skip = True
                            break
                    if not should_skip:
                        new_lines.append(line)
                app_v2.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _apply_override_zips(self):
        """
        Applies ZIP overrides and file removals based on replacements.json,
        supporting conditional execution with enhanced condition evaluation.

        Supports:
        - Simple conditions (legacy compatibility)
        - Composite conditions (and/or/not)
        - Dependency resolution between rules
        - Detailed failure reporting
        """
        rules_config = self._load_merged_config("replacements.json")
        if not rules_config:
            return

        override_rules = rules_config.get("replacements", [])
        if not override_rules:
            return

        # Resolve dependencies between rules
        try:
            merger = ConfigMerger()
            override_rules = merger.resolve_dependencies(override_rules)
        except Exception as e:
            self.logger.warning(f"Dependency resolution warning: {e}")

        self.logger.info("Applying ZIP overrides and file removals...")

        # Build condition context
        cond_ctx = self._build_condition_context()
        evaluator = ConditionEvaluator()

        applied_count = 0
        skipped_count = 0

        for rule in override_rules:
            rule_type = rule.get("type")
            description = rule.get("description", "Unnamed override")

            # Use enhanced condition evaluator
            if not evaluator.evaluate(rule, cond_ctx):
                self.logger.debug(f"Skipping rule '{description}': conditions not met")
                skipped_count += 1
                continue

            self.logger.info(f"Applying: {description}")

            if rule_type == "unzip_override":
                self._execute_unzip_override(rule)
                applied_count += 1
            elif rule_type == "remove_files":
                self._execute_remove_files(rule)
                applied_count += 1
            elif rule_type == "copy_file_internal":
                self._execute_copy_file_internal(rule)
                applied_count += 1
            elif rule_type == "copy_files_from_stock":
                self._execute_copy_files_from_stock(rule)
                applied_count += 1
            elif rule_type == "conditional_copy":
                self._execute_conditional_copy(rule)
                applied_count += 1
            elif rule_type == "overlay_sync":
                self._execute_overlay_sync(rule)
                applied_count += 1
            elif rule_type == "unzip_override_group":
                self.logger.info(f"Processing override group: {description}")
                group_applied = 0

                for op in rule.get("operations", []):
                    op_type = op.get("type")

                    # Evaluate nested conditions
                    if not evaluator.evaluate(op, cond_ctx):
                        op_desc = op.get("description", "unnamed operation")
                        self.logger.debug(
                            f"  Skipping operation '{op_desc}': conditions not met"
                        )
                        continue

                    if op_type == "unzip_override":
                        self._execute_unzip_override(op)
                        group_applied += 1
                    elif op_type == "remove_files":
                        self._execute_remove_files(op)
                        group_applied += 1
                    elif op_type == "copy_file_internal":
                        self._execute_copy_file_internal(op)
                        group_applied += 1
                    else:
                        self.logger.debug(
                            f"  Skipping unknown operation type: {op_type}"
                        )

                applied_count += group_applied
            else:
                self.logger.debug(f"Skipping unknown override rule type: {rule_type}")

        self.logger.info(
            f"Applied {applied_count} override rules, skipped {skipped_count}"
        )

    def _execute_copy_file_internal(self, rule):
        """Copies a file from one place in the target ROM to another."""
        src_rel = rule.get("source")
        dst_rel = rule.get("target")
        target_dir = self.ctx.target_dir

        src_path = target_dir / src_rel
        dst_path = target_dir / dst_rel

        # Condition: Destination path's existence (simulating if [[ -f dst ]])
        cond_dst_exists = rule.get("condition_target_exists", False)
        if cond_dst_exists and not dst_path.exists():
            return

        if src_path.exists():
            self.logger.info(f"  Copying internal: {src_rel} -> {dst_rel}")
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dst_path)
        else:
            self.logger.warning(f"  Internal copy source not found: {src_path}")

    def _execute_copy_files_from_stock(self, rule):
        """Copies files from baserom (stock) to target (portrom) with glob pattern support.

        Example:
        {
            "type": "copy_files_from_stock",
            "source": "my_product/etc/Multimedia_*.xml",
            "target_dir": "my_product/etc/",
            "description": "Copy Multimedia XML files"
        }
        """
        source_pattern = rule.get("source")
        target_dir_rel = rule.get("target_dir", "")
        description = rule.get("description", "Copy files from stock")

        if not source_pattern:
            self.logger.warning(f"  No source pattern specified for: {description}")
            return

        # Source is relative to stock (baserom) extracted directory
        stock_base = self.ctx.stock.extracted_dir
        source_path = stock_base / source_pattern

        # Target is relative to target_dir
        target_base = self.ctx.target_dir
        target_path = target_base / target_dir_rel

        # Use glob to find matching files
        import glob

        source_files = list(stock_base.glob(source_pattern))

        if not source_files:
            self.logger.debug(f"  No files matching pattern: {source_pattern}")
            return

        self.logger.info(f"  {description}: copying {len(source_files)} file(s)")
        target_path.mkdir(parents=True, exist_ok=True)

        copied_count = 0
        for src_file in source_files:
            if src_file.is_file():
                dst_file = target_path / src_file.name
                try:
                    shutil.copy2(src_file, dst_file)
                    self.logger.debug(f"    Copied: {src_file.name}")
                    copied_count += 1
                except Exception as e:
                    self.logger.warning(f"    Failed to copy {src_file.name}: {e}")

        self.logger.info(f"  Copied {copied_count} file(s) to {target_dir_rel}")

    def _execute_conditional_copy(self, rule):
        """Conditionally copy file from baserom to portrom or remove from portrom.

        If the source file exists in baserom, copy it to portrom.
        If the source file doesn't exist in baserom, remove it from portrom if it exists.

        Example:
        {
            "type": "conditional_copy",
            "source": "my_product/etc/extension/sys_graphic_enhancement_config.json",
            "target": "my_product/etc/extension/sys_graphic_enhancement_config.json",
            "description": "Copy sys_graphic_enhancement_config.json if exists in baserom"
        }
        """
        source_rel = rule.get("source")
        target_rel = rule.get("target")
        description = rule.get("description", "Conditional copy")

        if not source_rel or not target_rel:
            self.logger.warning(f"  Missing source or target for: {description}")
            return

        # Source is relative to stock (baserom) extracted directory
        stock_base = self.ctx.stock.extracted_dir
        source_path = stock_base / source_rel

        # Target is relative to target_dir (portrom)
        target_base = self.ctx.target_dir
        target_path = target_base / target_rel

        if source_path.exists():
            # Source exists in baserom, copy to portrom
            self.logger.info(f"  {description}: copying from baserom")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if source_path.is_dir():
                    shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(source_path, target_path)
                self.logger.info(f"    Copied: {source_rel} -> {target_rel}")
            except Exception as e:
                self.logger.warning(f"    Failed to copy {source_rel}: {e}")
        else:
            # Source doesn't exist in baserom, remove from portrom if it exists
            self.logger.info(
                f"  {description}: source not in baserom, removing from portrom if exists"
            )
            if target_path.exists():
                try:
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                    else:
                        target_path.unlink()
                    self.logger.info(f"    Removed: {target_rel}")
                except Exception as e:
                    self.logger.warning(f"    Failed to remove {target_rel}: {e}")
            else:
                self.logger.debug(
                    f"    Target doesn't exist, nothing to remove: {target_rel}"
                )

    def _execute_overlay_sync(self, rule):
        """
        Sync overlay files from baserom to portrom with pattern matching and cleanup.

        This handles the complex overlay sync logic from port.sh:
        1. Copy vendor directory from baserom
        2. Remove matching overlay files from portrom
        3. Copy matching overlay files from baserom

        Example:
        {
            "type": "overlay_sync",
            "copy_vendor": true,
            "remove_patterns": ["*display*[0-9]*.apk"],
            "overlay_pattern": "*{my_product_type}*.apk",
            "description": "Sync overlay files from baserom"
        }
        """
        description = rule.get("description", "Overlay sync")
        copy_vendor = rule.get("copy_vendor", False)
        remove_patterns = rule.get("remove_patterns", [])
        overlay_pattern = rule.get("overlay_pattern", "")

        # Get variable substitutions from context
        var_substitutions = {
            "my_product_type": getattr(self.ctx, "base_my_product_type", ""),
            "base_product_device": getattr(self.ctx, "base_product_device", ""),
            "device_code": getattr(self.ctx, "base_device_code", ""),
        }

        # Apply variable substitution to pattern
        if overlay_pattern:
            for var_name, var_value in var_substitutions.items():
                if var_value:
                    placeholder = f"{{{var_name}}}"
                    overlay_pattern = overlay_pattern.replace(
                        placeholder, str(var_value)
                    )

        self.logger.info(f"  {description}")

        stock_base = self.ctx.stock.extracted_dir
        target_base = self.ctx.target_dir

        # 1. Copy vendor directory if requested
        if copy_vendor:
            vendor_source = stock_base / "my_product" / "vendor"
            vendor_target = target_base / "my_product" / "vendor"

            if vendor_source.exists():
                self.logger.info(f"    Copying vendor directory from baserom")
                try:
                    if vendor_target.exists():
                        shutil.rmtree(vendor_target)
                    shutil.copytree(vendor_source, vendor_target)
                    self.logger.info(f"    Copied vendor directory")
                except Exception as e:
                    self.logger.warning(f"    Failed to copy vendor directory: {e}")
            else:
                self.logger.debug(f"    Vendor directory not found in baserom")

        # 2. Remove matching overlay files from portrom
        overlay_target_dir = target_base / "my_product" / "overlay"
        if overlay_target_dir.exists() and remove_patterns:
            for pattern in remove_patterns:
                try:
                    matched_files = list(overlay_target_dir.glob(pattern))
                    for file_path in matched_files:
                        if file_path.exists():
                            if file_path.is_dir():
                                shutil.rmtree(file_path)
                            else:
                                file_path.unlink()
                            self.logger.info(f"    Removed: {file_path.name}")
                except Exception as e:
                    self.logger.warning(
                        f"    Failed to remove files matching {pattern}: {e}"
                    )

        # 3. Copy matching overlay files from baserom to portrom
        if overlay_pattern:
            # Search in all baserom image directories
            copied_count = 0
            for search_dir in stock_base.rglob("my_product/overlay"):
                if search_dir.exists():
                    try:
                        matched_files = list(search_dir.glob(overlay_pattern))
                        for source_file in matched_files:
                            if source_file.is_file():
                                target_file = overlay_target_dir / source_file.name
                                overlay_target_dir.mkdir(parents=True, exist_ok=True)
                                try:
                                    shutil.copy2(source_file, target_file)
                                    self.logger.info(
                                        f"    Copied overlay: {source_file.name}"
                                    )
                                    copied_count += 1
                                except Exception as e:
                                    self.logger.warning(
                                        f"    Failed to copy {source_file.name}: {e}"
                                    )
                    except Exception as e:
                        self.logger.warning(f"    Failed to search {search_dir}: {e}")

            if copied_count > 0:
                self.logger.info(f"    Total overlay files copied: {copied_count}")

    def _execute_unzip_override(self, rule):
        source_zip = Path(rule["source"])
        target_base_dir = self.ctx.work_dir / rule.get("target_base_dir", "")

        # Ensure asset exists (download if missing)
        if not self.ctx.assets.ensure_asset(source_zip):
            self.logger.warning(
                f"Override ZIP not found and download failed: {source_zip}, skipping."
            )
            return

        self.logger.info(f"  Unzipping '{source_zip.name}' to '{target_base_dir}'")
        try:
            with zipfile.ZipFile(source_zip, "r") as z:
                z.extractall(target_base_dir)
            self.logger.info(f"  Successfully extracted {source_zip.name}")
        except Exception as e:
            self.logger.error(f"  Failed to extract {source_zip.name}: {e}")
            return

        # Process removals AFTER unzip
        removes = rule.get("removes", [])
        if removes:
            self.logger.info(f"  Removing {len(removes)} patterns after unzip...")
            effective_base_dir_for_removes = target_base_dir
            for pattern in removes:
                # Support glob patterns
                matched = (
                    list(effective_base_dir_for_removes.glob(pattern))
                    if "*" in str(pattern)
                    else [effective_base_dir_for_removes / pattern]
                )
                for full_path in matched:
                    if full_path.exists():
                        if full_path.is_dir():
                            shutil.rmtree(full_path)
                            self.logger.debug(f"    Removed directory: {full_path}")
                        else:
                            full_path.unlink()
                            self.logger.debug(f"    Removed file: {full_path}")

        # Process build_props in rule
        rule_props = rule.get("build_props")
        if rule_props:
            self._apply_build_props(rule_props)

    def _execute_remove_files(self, rule):
        files_to_remove = rule.get("files", [])
        if files_to_remove:
            self.logger.info(f"  Removing {len(files_to_remove)} specified patterns...")
            effective_base_dir_for_removes = self.ctx.work_dir / rule.get(
                "target_base_dir", ""
            )
            for pattern in files_to_remove:
                # Support glob patterns
                matched = (
                    list(effective_base_dir_for_removes.glob(pattern))
                    if "*" in str(pattern)
                    else [effective_base_dir_for_removes / pattern]
                )
                for full_path in matched:
                    if full_path.exists():
                        if full_path.is_dir():
                            shutil.rmtree(full_path)
                            self.logger.debug(f"    Removed directory: {full_path}")
                        else:
                            full_path.unlink()
                            self.logger.debug(f"    Removed file: {full_path}")

    def _build_target_index(self, root: Path):
        """Build a cache of all files and directories in the target root for faster lookup"""
        self.logger.debug(f"Indexing target directory: {root}")
        index = {}
        if not root.exists():
            return index

        for item in root.rglob("*"):
            name = item.name
            if name not in index:
                index[name] = []
            index[name].append(item)
        return index

    def _deep_merge(self, base: dict | list, extra: dict | list):
        """Recursively merges extra into base. (Legacy method, kept for compatibility)"""
        if isinstance(base, dict) and isinstance(extra, dict):
            for key, value in extra.items():
                if (
                    key in base
                    and isinstance(base[key], (dict, list))
                    and isinstance(value, (dict, list))
                ):
                    self._deep_merge(base[key], value)
                else:
                    base[key] = value
        elif isinstance(base, list) and isinstance(extra, list):
            for item in extra:
                if item not in base:
                    base.append(item)
        return base

    def _load_merged_config(self, filename: str):
        """
        Load and merge config from Common -> Chipset -> Target layers.
        Enhanced with validation, detailed reporting, and improved error handling.
        """
        # Build paths for hierarchical config loading
        paths = [Path("devices/common") / filename]

        if (
            hasattr(self.ctx, "base_chipset_family")
            and self.ctx.base_chipset_family != "unknown"
        ):
            paths.append(
                Path(f"devices/chipset/{self.ctx.base_chipset_family}") / filename
            )

        if hasattr(self.ctx, "base_device_code") and self.ctx.base_device_code:
            device_id = self.ctx.base_device_code.upper()
            paths.append(Path(f"devices/target/{device_id}") / filename)

        # Use enhanced ConfigMerger
        merger = ConfigMerger(logger=self.logger)
        config, report = merger.load_and_merge(paths, filename)

        # Log merge report
        if report.loaded_files:
            self.logger.info(
                f"Config '{filename}' loaded from {len(report.loaded_files)} layer(s)"
            )
        if report.missing_files:
            self.logger.debug(
                f"Config '{filename}' missing (expected): {len(report.missing_files)} file(s)"
            )
        if report.warnings:
            for warn in report.warnings:
                self.logger.warning(f"Config '{filename}': {warn}")
        if report.errors:
            for err in report.errors:
                self.logger.error(f"Config '{filename}': {err}")

        # Validate loaded config (skip if already validated during load)
        # Config merger already handles validation, this is redundant

        return config

    def _build_condition_context(self) -> BuildContext:
        """
        Build a condition context from the current build context.
        This bridges the old context attributes to the new condition system.
        """
        ctx = BuildContext()

        # Copy ROM type flags
        ctx.portIsColorOS = getattr(self.ctx, "portIsColorOS", False)
        ctx.portIsColorOSGlobal = getattr(self.ctx, "portIsColorOSGlobal", False)
        ctx.portIsOOS = getattr(self.ctx, "portIsOOS", False)

        # Copy version info
        ctx.port_android_version = int(getattr(self.ctx, "port_android_version", 14))
        ctx.base_android_version = int(getattr(self.ctx, "base_android_version", 14))
        ctx.port_oplusrom_version = str(getattr(self.ctx, "port_oplusrom_version", ""))

        # Copy region and chipset info
        ctx.base_regionmark = str(getattr(self.ctx, "base_regionmark", ""))
        ctx.base_chipset_family = str(
            getattr(self.ctx, "base_chipset_family", "unknown")
        )
        ctx.base_device_code = str(getattr(self.ctx, "base_device_code", ""))

        return ctx

    def _process_replacements(self):
        """
        Execute file/directory replacements defined in replacements.json.
        Supports types: file, dir, package (by APK package name)
        """
        replacements = self._load_merged_config("replacements.json")
        if not replacements:
            return

        self.logger.info("Processing file replacements...")

        stock_root = self.ctx.stock.extracted_dir
        target_root = self.ctx.target_dir

        # Pre-scan target directory for fast recursive lookups
        target_index = self._build_target_index(target_root)

        # Build condition context and create evaluator
        cond_ctx = self._build_condition_context()
        evaluator = ConditionEvaluator()

        def _handle_copy_op(src_item, target_item, rel_name):
            self.logger.info(f"  Replacing/Adding: {rel_name}")
            if not target_item.parent.exists():
                target_item.parent.mkdir(parents=True, exist_ok=True)

            if target_item.exists():
                if target_item.is_dir():
                    shutil.rmtree(target_item)
                else:
                    target_item.unlink()

            if src_item.is_dir():
                shutil.copytree(
                    src_item, target_item, symlinks=True, dirs_exist_ok=True
                )
            else:
                shutil.copy2(src_item, target_item)

        copy_tasks = []

        if isinstance(replacements, dict):
            # If the json is a dict with a list inside, or just list
            rules = (
                replacements.get("replacements", [])
                if isinstance(replacements, dict)
                else replacements
            )
        else:
            rules = replacements

        for rule in rules:
            desc = rule.get("description", "Unknown Rule")

            # Use enhanced condition evaluator
            if not evaluator.evaluate(rule, cond_ctx):
                self.logger.debug(f"Skipping rule '{desc}': conditions not met")
                continue

            rtype = rule.get("type", "file")
            search_path = rule.get("search_path", "")
            match_mode = rule.get("match_mode", "exact")
            ensure_exists = rule.get("ensure_exists", False)
            files = rule.get("files", [])

            self.logger.info(f"Applying rule: {desc}")

            if rtype == "package":
                self._process_package_replacement(rule, desc, stock_root, target_root)
                continue

            rule_stock_root = stock_root / search_path
            rule_target_root = target_root / search_path

            if not rule_stock_root.exists():
                self.logger.debug(f"Source path not found: {rule_stock_root}")
                continue

            for pattern in files:
                sources = []
                if match_mode == "glob":
                    sources = list(rule_stock_root.glob(pattern))
                elif match_mode == "recursive":
                    sources = list(rule_stock_root.rglob(pattern))
                else:
                    exact_file = rule_stock_root / pattern
                    if exact_file.exists():
                        sources = [exact_file]

                if not sources:
                    self.logger.debug(f"No source items found for pattern: {pattern}")
                    continue

                for src_item in sources:
                    rel_name = src_item.name
                    target_item = rule_target_root / rel_name

                    found_in_target = False

                    if match_mode == "recursive":
                        # Use target_index for fast lookup
                        candidates = target_index.get(rel_name, [])
                        if candidates:
                            # Prefer candidate that is under the rule_target_root if possible
                            best_match = None
                            for cand in candidates:
                                try:
                                    cand.relative_to(rule_target_root)
                                    best_match = cand
                                    break
                                except ValueError:
                                    continue

                            if best_match:
                                target_item = best_match
                                found_in_target = True
                            else:
                                # If no candidate under rule_target_root, use the first one found
                                target_item = candidates[0]
                                found_in_target = True
                    else:
                        if target_item.exists():
                            found_in_target = True

                    should_copy = False
                    if found_in_target:
                        should_copy = True
                    elif ensure_exists:
                        should_copy = True
                        if match_mode == "recursive":
                            try:
                                rel = src_item.relative_to(rule_stock_root)
                                target_item = rule_target_root / rel
                            except:
                                pass

                    if should_copy:
                        copy_tasks.append((src_item, target_item, rel_name))
                    else:
                        self.logger.debug(
                            f"  Skipping {rel_name} (Target missing and ensure_exists=False)"
                        )

        # Execute all copy operations in parallel with dynamic worker count
        if copy_tasks:
            self.logger.info(
                f"Executing {len(copy_tasks)} replacement tasks in parallel..."
            )
            # Dynamic worker count based on task count and CPU
            cpu_count = os.cpu_count() or 4
            # For file copy operations, use more workers as they are I/O bound
            max_workers = min(max(cpu_count, len(copy_tasks) // 5 + 1), 8)

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                futures = [
                    executor.submit(_handle_copy_op, *task) for task in copy_tasks
                ]
                # Track completion with progress
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    completed += 1
                    if completed % 10 == 0 or completed == len(copy_tasks):
                        self.logger.debug(
                            f"  Replacement progress: {completed}/{len(copy_tasks)}"
                        )

                # Check for exceptions
                for future in futures:
                    try:
                        future.result()
                    except Exception as e:
                        self.logger.error(f"Replacement task failed: {e}")
                        raise

    def _process_package_replacement(self, rule, desc, stock_root, target_root):
        """Process replacements by APK package name"""
        search_path = rule.get("search_path", "")
        files = rule.get("files", [])

        # scan_apks is cached in RomPackage, so this is fast
        stock_apks = self.ctx.stock.scan_apks()
        target_apks = self.ctx.port.scan_apks()

        rule_target_root = target_root / search_path

        for pkg_name in files:
            stock_apk_info = stock_apks.get(pkg_name)
            target_apk_info = target_apks.get(pkg_name)

            if not stock_apk_info:
                self.logger.debug(f"Package {pkg_name} not found in stock ROM")
                continue

            src_path = stock_apk_info["path"]

            if target_apk_info:
                dst_path = target_apk_info["path"]
                self.logger.info(f"  Replacing {pkg_name}: {dst_path.name}")
            else:
                dst_path = rule_target_root / src_path.name
                self.logger.info(f"  Adding {pkg_name}: {dst_path.name}")

            if not dst_path.parent.exists():
                dst_path.parent.mkdir(parents=True, exist_ok=True)

            if dst_path.exists():
                if dst_path.is_dir():
                    shutil.rmtree(dst_path)
                else:
                    dst_path.unlink()

            shutil.copy2(src_path, dst_path)

    def _get_package_name(self, apk_path):
        try:
            # Use self.shell.run to handle binary pathing and LD_LIBRARY_PATH
            # aapt2 dump packagename <apk>
            # Output: package: name='com.android.chrome'
            result = self.shell.run(
                ["aapt2", "dump", "packagename", str(apk_path)],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                # Parse "package: name='com.foo.bar'"
                if "package: name=" in output:
                    return output.split("'")[1]
            return None
        except Exception:
            return None

    def _apply_coloros_features(self):
        """
        Apply ColorOS specific XML features - port.sh add_feature_v2 logic
        Handles oplus_feature, app_feature, permission_feature, permission_oplus_feature
        Supports conditional features based on device properties
        """
        self.logger.info("Applying ColorOS XML features...")

        # Load ColorOS features config using hierarchical merge
        config = self._load_merged_config("features.json")
        if not config:
            self.logger.info("No ColorOS features config found, skipping.")
            return

        # Import condition evaluator
        from src.core.conditions import ConditionEvaluator, BuildContext

        # Create a build context from PortingContext
        build_ctx = BuildContext()
        build_ctx.portIsColorOS = getattr(self.ctx, "portIsColorOS", False)
        build_ctx.portIsColorOSGlobal = getattr(self.ctx, "portIsColorOSGlobal", False)
        build_ctx.portIsOOS = getattr(self.ctx, "portIsOOS", False)
        build_ctx.port_android_version = int(
            getattr(self.ctx, "port_android_version", 0) or 0
        )
        build_ctx.base_android_version = int(
            getattr(self.ctx, "base_android_version", 0) or 0
        )
        build_ctx.port_oplusrom_version = getattr(self.ctx, "port_oplusrom_version", "")
        build_ctx.base_regionmark = getattr(self.ctx, "base_regionmark", "")
        build_ctx.base_chipset_family = getattr(self.ctx, "base_chipset_family", "")
        build_ctx.base_device_code = getattr(self.ctx, "base_device_code", "")

        self.logger.info(
            f"DEBUG: base_android_version = {build_ctx.base_android_version}, port_android_version = {build_ctx.port_android_version}"
        )

        evaluator = ConditionEvaluator()

        # Apply each feature type
        self._apply_coloros_xml_features(
            config.get("oplus_feature", []), "oplus_feature"
        )
        self._apply_coloros_xml_features(config.get("app_feature", []), "app_feature")
        self._apply_coloros_xml_features(
            config.get("permission_feature", []), "permission_feature"
        )
        self._apply_coloros_xml_features(
            config.get("permission_oplus_feature", []), "permission_oplus_feature"
        )

        # Apply conditional features
        for feature_type in [
            "oplus_feature",
            "app_feature",
            "permission_feature",
            "permission_oplus_feature",
        ]:
            conditional_key = f"{feature_type}_conditional"
            conditional_features = config.get(conditional_key, [])
            for item in conditional_features:
                if isinstance(item, dict) and "feature" in item:
                    condition = item.get("condition", {})
                    # Wrap condition in proper format for evaluator
                    result = evaluator.evaluate({"condition": condition}, build_ctx)
                    self.logger.info(
                        f"DEBUG: Evaluating {item['feature'][:50]}... with condition {condition} -> {result}"
                    )
                    if result:
                        self._apply_coloros_xml_features(
                            [item["feature"]], feature_type
                        )
                        self.logger.info(
                            f"Applied conditional feature: {item['feature']}"
                        )
                    else:
                        self.logger.info(
                            f"Skipped conditional feature: {item['feature']}"
                        )

        # Remove features from XML (unconditional)
        features_remove = config.get("features_remove", [])
        if features_remove:
            self._remove_features_from_xml(features_remove)

        # Remove conditional features
        features_remove_conditional = config.get("features_remove_conditional", [])
        for item in features_remove_conditional:
            if isinstance(item, dict) and "features" in item:
                condition = item.get("condition", {})
                # Wrap condition in proper format for evaluator
                result = evaluator.evaluate({"condition": condition}, build_ctx)
                self.logger.info(
                    f"DEBUG: Evaluating removal with condition {condition} -> {result}"
                )
                if result:
                    self._remove_features_from_xml(item["features"])
                    self.logger.info(
                        f"Removed conditional features: {item['features']}"
                    )
                else:
                    self.logger.info(
                        f"Skipped removal of conditional features: {item['features']}"
                    )

        # Remove features with force mode (ignore baserom check)
        features_remove_force = config.get("features_remove_force", [])
        if features_remove_force:
            self.logger.info(
                f"Force removing {len(features_remove_force)} features (ignoring baserom check)..."
            )
            self._remove_features_from_xml(features_remove_force, force=True)

        # Apply props remove/add
        props_remove = config.get("props_remove", [])
        if props_remove:
            self._remove_build_props(props_remove)

        props_add = config.get("props_add", {})
        if props_add:
            self._apply_build_props(props_add)

    def _apply_coloros_xml_features(self, features: list, feature_type: str):
        """Apply ColorOS XML features - port.sh add_feature_v2 logic"""
        if not features:
            return

        # Determine target directory and file based on feature type
        target_dir = self.ctx.target_dir / "my_product" / "etc"

        if feature_type == "oplus_feature":
            xml_dir = target_dir / "extension"
            base_file = "com.oplus.oplus-feature"
            root_tag = "oplus-config"
            node_tag = "oplus-feature"
        elif feature_type == "app_feature":
            xml_dir = target_dir / "extension"
            base_file = "com.oplus.app-features"
            root_tag = "extend_features"
            node_tag = "app_feature"
        elif feature_type == "permission_feature":
            xml_dir = target_dir / "permissions"
            base_file = "com.oplus.android-features"
            root_tag = "permissions"
            node_tag = "feature"
        elif feature_type == "permission_oplus_feature":
            xml_dir = target_dir / "permissions"
            base_file = "oplus.feature-android"
            root_tag = "oplus-config"
            node_tag = "oplus-feature"
        else:
            return

        xml_dir.mkdir(parents=True, exist_ok=True)
        output_file = xml_dir / f"{base_file}-ext.xml"

        # Create file if not exists
        if not output_file.exists():
            content = (
                f'<?xml version="1.0" encoding="UTF-8"?>\n<{root_tag}>\n</{root_tag}>\n'
            )
            output_file.write_text(content, encoding="utf-8")

        # Read existing content
        content = output_file.read_text(encoding="utf-8")

        for entry in features:
            # Parse entry: "feature^comment^args" or just "feature"
            parts = entry.split("^")
            feature = parts[0].strip()
            comment = parts[1].strip() if len(parts) > 1 and parts[1] else ""
            extra = parts[2].strip() if len(parts) > 2 else ""

            # Check if feature already exists in any XML
            exists = self._check_feature_exists(feature)
            if exists:
                self.logger.info(f"Feature {feature} already exists, skipping.")
                continue

            # Add feature
            self.logger.info(f"Adding feature: {feature}")

            # Build attribute string
            attrs = f'name="{feature}"'
            if extra:
                # Handle args=\"boolean:true\" etc
                # If extra starts with args=, it's already formatted
                if extra.startswith("args="):
                    attrs = f"{attrs} {extra}"
                else:
                    attrs = f"{attrs} {extra}"

            # Add comment before feature
            if comment:
                comment_line = f"    <!-- {comment} -->\n"
                content = content.replace(
                    f"</{root_tag}>",
                    comment_line + f"    <{node_tag} {attrs}/>\n</{root_tag}>",
                )
            else:
                content = content.replace(
                    f"</{root_tag}>", f"    <{node_tag} {attrs}/>\n</{root_tag}>"
                )

        output_file.write_text(content, encoding="utf-8")

    def _check_feature_exists(self, feature: str) -> bool:
        """Check if feature already exists in any XML file"""
        my_product_etc = self.ctx.target_dir / "my_product" / "etc"
        if not my_product_etc.exists():
            return False

        for xml_file in my_product_etc.rglob("*.xml"):
            try:
                content = xml_file.read_text(encoding="utf-8", errors="ignore")
                if feature in content:
                    return True
            except Exception:
                pass
        return False

    def _remove_build_props(self, props_to_remove: list, force: bool = False):
        """Remove properties from build.prop files
        Only removes if prop doesn't exist in baserom (or is commented out), unless force=True
        """
        target_dirs = [
            self.ctx.target_dir / "my_product",
            self.ctx.target_dir / "my_manifest",
            self.ctx.target_dir / "system" / "system",
            self.ctx.target_dir / "vendor",
        ]

        # First check which props exist in baserom (uncommented)
        baserom_props = set()
        baserom_props_commented = set()

        baserom_dirs = [
            self.ctx.stock.extracted_dir / "my_product",
            self.ctx.stock.extracted_dir / "my_manifest",
            self.ctx.stock.extracted_dir / "system" / "system",
            self.ctx.stock.extracted_dir / "vendor",
        ]

        if not force:
            for baserom_dir in baserom_dirs:
                build_prop = baserom_dir / "build.prop"
                if not build_prop.exists():
                    continue
                try:
                    content = build_prop.read_text(encoding="utf-8", errors="ignore")
                    for prop in props_to_remove:
                        if f"{prop}=" in content:
                            # Check if commented
                            for line in content.split("\n"):
                                stripped = line.strip()
                                if stripped.startswith(f"{prop}="):
                                    baserom_props.add(prop)
                                elif stripped.startswith(f"#") and prop in stripped:
                                    baserom_props_commented.add(prop)
                except Exception:
                    pass

        for target_dir in target_dirs:
            build_prop = target_dir / "build.prop"
            if not build_prop.exists():
                continue

            content = build_prop.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            new_lines = []

            for line in lines:
                should_remove = False
                for prop in props_to_remove:
                    if line.strip().startswith(prop + "="):
                        # Check if should remove based on baserom
                        if force:
                            should_remove = True
                        elif prop in baserom_props:
                            # Exists in baserom, skip
                            self.logger.info(
                                f"Prop {prop} exists in baserom, skipping removal"
                            )
                            should_remove = False
                        elif prop in baserom_props_commented:
                            # Commented in baserom, can remove
                            should_remove = True
                        else:
                            # Doesn't exist in baserom
                            should_remove = True

                        if should_remove:
                            self.logger.info(f"Removing prop: {prop}")
                        break

                if not should_remove:
                    new_lines.append(line)

            build_prop.write_text("\n".join(new_lines), encoding="utf-8")

    def _fix_dolby_audio(self):
        """Fix Dolby audio and multi-app volume - port.sh line 1417-1422"""
        self.logger.info("Checking for Dolby audio fix...")

        baserom = self.ctx.stock.extracted_dir
        target = self.ctx.target_dir

        # Check if baserom has dolby effect type
        dolby_prop = baserom / "my_product" / "build.prop"
        if not dolby_prop.exists():
            return

        content = dolby_prop.read_text(encoding="utf-8", errors="ignore")
        if "ro.oplus.audio.effect.type=dolby" not in content:
            return

        self.logger.info("Applying Dolby audio fix...")

        # Copy dolby xml
        dolby_xml = (
            baserom
            / "my_product"
            / "etc"
            / "permissions"
            / "oplus.product.features_dolby_stereo.xml"
        )
        target_xml = (
            target
            / "my_product"
            / "etc"
            / "permissions"
            / "oplus.product.features_dolby_stereo.xml"
        )
        if dolby_xml.exists():
            shutil.copy2(dolby_xml, target_xml)

        # Try to extract dolby_fix.zip from devices/common if exists
        dolby_zip = Path("devices/common/dolby_fix.zip")
        if self.ctx.assets.ensure_asset(dolby_zip):
            try:
                with zipfile.ZipFile(dolby_zip, "r") as z:
                    z.extractall(target)
                self.logger.info("Extracted dolby_fix.zip")
            except Exception as e:
                self.logger.warning(f"Failed to extract dolby_fix.zip: {e}")

    def _apply_ai_memory(self):
        """Apply AI Memory and AppBooster - port.sh line 1733-1754"""
        self.logger.info("Applying AI Memory / AppBooster...")

        target = self.ctx.target_dir
        ai_memory_zip = Path("devices/common/ai_memory.zip")
        ai_memory_in_zip = Path("devices/common/ai_memory_in/aimemory.zip")

        # Determine which zip to use based on region
        regionmark = getattr(self.ctx, "regionmark", "CN")

        if regionmark == "CN":
            if self.ctx.assets.ensure_asset(ai_memory_zip):
                try:
                    with zipfile.ZipFile(ai_memory_zip, "r") as z:
                        z.extractall(target)
                    self.logger.info("Extracted ai_memory.zip")
                except Exception as e:
                    self.logger.warning(f"Failed to extract ai_memory.zip: {e}")
        else:
            if self.ctx.assets.ensure_asset(ai_memory_in_zip):
                try:
                    with zipfile.ZipFile(ai_memory_in_zip, "r") as z:
                        z.extractall(target)
                    self.logger.info("Extracted ai_memory_in/aimemory.zip")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to extract ai_memory_in/aimemory.zip: {e}"
                    )

        # Enable AIMemory and AppBooster in app_v2.xml
        app_v2 = target / "my_product" / "etc" / "config" / "app_v2.xml"
        if app_v2.exists():
            content = app_v2.read_text(encoding="utf-8", errors="ignore")
            for pkg in ["com.oplus.aimemory", "com.oplus.appbooster"]:
                if f'<enable pkg="{pkg}"' not in content:
                    content = content.replace(
                        "</app>", f'  <enable pkg="{pkg}" priority="7"/>\n</app>'
                    )
            app_v2.write_text(content, encoding="utf-8")

    def _remove_features_from_xml(self, features: list, force: bool = False):
        """Remove features from XML - port.sh remove_feature function
        Only removes if feature doesn't exist in baserom (or is commented out), unless force=True
        """
        my_product_etc = self.ctx.target_dir / "my_product" / "etc"
        baserom_etc = self.ctx.stock.extracted_dir / "my_product" / "etc"

        if not my_product_etc.exists():
            return

        for feature in features:
            should_remove = False

            if force:
                # Force mode: always remove
                should_remove = True
            elif baserom_etc.exists():
                # Check if feature exists in baserom
                baserom_has_feature = False
                baserom_feature_commented = False

                for xml_file in baserom_etc.rglob("*.xml"):
                    try:
                        content = xml_file.read_text(encoding="utf-8", errors="ignore")
                        # Check if feature exists and is not commented
                        if feature in content:
                            if (
                                f"<!--{feature}" in content
                                or f"<!-- {feature}" in content
                            ):
                                baserom_feature_commented = True
                            else:
                                baserom_has_feature = True
                                break
                    except Exception:
                        pass

                if baserom_has_feature:
                    self.logger.info(
                        f"Feature {feature} exists in baserom, skipping removal"
                    )
                    continue
                elif baserom_feature_commented:
                    self.logger.info(
                        f"Feature {feature} is commented in baserom, will remove from portrom"
                    )
                    should_remove = True
                else:
                    # Feature doesn't exist in baserom, safe to remove
                    should_remove = True
            else:
                # Baserom dir doesn't exist, safe to remove
                should_remove = True

            if should_remove:
                for xml_file in my_product_etc.rglob("*.xml"):
                    try:
                        content = xml_file.read_text(encoding="utf-8", errors="ignore")
                        if feature in content:
                            content = content.replace(feature, "")
                            # Also remove empty lines
                            content = re.sub(r"^\s*$", "", content, flags=re.MULTILINE)
                            xml_file.write_text(content, encoding="utf-8")
                            self.logger.info(
                                f"Removed feature {feature} from {xml_file.name}"
                            )
                    except Exception:
                        pass

    def _apply_xml_features(self, features):
        feat_dir = self.ctx.target_dir / "product/etc/device_features"
        if not feat_dir.exists():
            self.logger.warning("device_features directory not found.")
            return

        # Target file: usually matches stock code, or just find any XML
        xml_file = feat_dir / f"{self.ctx.stock_rom_code}.xml"
        if not xml_file.exists():
            # Fallback: try finding any XML in the folder
            try:
                xml_file = next(feat_dir.glob("*.xml"))
            except StopIteration:
                self.logger.warning("No device features XML found.")
                return

        self.logger.info(f"Modifying features in {xml_file.name}...")
        content = xml_file.read_text(encoding="utf-8")

        modified = False
        for name, value in features.items():
            str_value = str(value).lower()  # true/false

            # Check existence
            # Regex to find <bool name="feature_name">...</bool>
            pattern = re.compile(rf'<bool name="{re.escape(name)}">.*?</bool>')

            if pattern.search(content):
                # Update existing
                new_tag = f'<bool name="{name}">{str_value}</bool>'
                new_content = pattern.sub(new_tag, content)
                if new_content != content:
                    content = new_content
                    modified = True
                    self.logger.debug(f"Updated feature: {name} = {str_value}")
            else:
                # Insert new (before </features>)
                if "</features>" in content:
                    new_tag = f'    <bool name="{name}">{str_value}</bool>\n</features>'
                    content = content.replace("</features>", new_tag)
                    modified = True
                    self.logger.debug(f"Added feature: {name} = {str_value}")

        if modified:
            xml_file.write_text(content, encoding="utf-8")

    def _apply_build_props(self, props_map):
        for partition, props in props_map.items():
            if partition == "vendor":
                prop_file = self.ctx.target_dir / "vendor/build.prop"
            elif partition == "product":
                prop_file = self.ctx.target_dir / "product/etc/build.prop"
            else:
                continue

            if not prop_file.exists():
                continue

            content = prop_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            new_lines = []

            # Simple parsing to avoid duplicates
            existing_keys = set()
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    existing_keys.add(line.split("=")[0].strip())
                new_lines.append(line)

            appended = False
            for key, value in props.items():
                if key not in existing_keys:
                    new_lines.append(f"{key}={value}")
                    self.logger.debug(f"Appended prop to {partition}: {key}={value}")
                    appended = True
                # If we wanted to update existing props, we'd need more complex logic here

            if appended:
                prop_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _find_file_recursive(self, root_dir: Path, filename: str) -> Path | None:
        cache_key = (str(root_dir), filename)
        if cache_key in self._file_cache:
            cached_path = self._file_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._file_cache[cache_key]

        if not root_dir.exists():
            return None
        try:
            result = next(root_dir.rglob(filename))
            self._file_cache[cache_key] = result
            return result
        except StopIteration:
            self._file_cache[cache_key] = None
            return None

    def _find_dir_recursive(self, root_dir: Path, dirname: str) -> Path | None:
        cache_key = (str(root_dir), dirname)
        if cache_key in self._dir_cache:
            cached_path = self._dir_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._dir_cache[cache_key]

        if not root_dir.exists():
            return None
        for p in root_dir.rglob(dirname):
            if p.is_dir() and p.name == dirname:
                self._dir_cache[cache_key] = p
                return p
        self._dir_cache[cache_key] = None
        return None

    def _apktool_decode(self, apk_path: Path, out_dir: Path):
        self.shell.run_java_jar(
            self.apktool, ["d", str(apk_path), "-o", str(out_dir), "-f"]
        )

    def _apktool_build(self, src_dir: Path, out_apk: Path):
        self.shell.run_java_jar(
            self.apktool, ["b", str(src_dir), "-o", str(out_apk), "-f"]
        )

    def _fix_vndk_apex(self):
        vndk_version = self.ctx.stock.get_prop("ro.vndk.version")

        if not vndk_version:
            for prop in (self.ctx.stock.extracted_dir / "vendor").rglob("*.prop"):
                try:
                    with open(prop, errors="ignore") as f:
                        for line in f:
                            if "ro.vndk.version=" in line:
                                vndk_version = line.split("=")[1].strip()
                                break
                except:
                    pass
                if vndk_version:
                    break

        if not vndk_version:
            return

        apex_name = f"com.android.vndk.v{vndk_version}.apex"
        stock_apex = self._find_file_recursive(
            self.ctx.stock.extracted_dir / "system_ext/apex", apex_name
        )
        target_apex_dir = self.ctx.target_dir / "system_ext/apex"

        if stock_apex and target_apex_dir.exists():
            target_file = target_apex_dir / apex_name
            if not target_file.exists():
                self.logger.info(f"Copying missing VNDK Apex: {apex_name}")
                shutil.copy2(stock_apex, target_file)

    def _apply_device_overrides(self):
        base_code = self.ctx.stock_rom_code
        port_ver = self.ctx.port_android_version

        override_src = Path(f"devices/{base_code}/override/{port_ver}").resolve()

        if not override_src.exists() or not override_src.is_dir():
            self.logger.warning(f"Device overlay dir not found: {override_src}")
            return

        self.logger.info(f"Applying device overrides from: {override_src}")

        has_nfc_override = False
        for f in override_src.rglob("*.apk"):
            name = f.name.lower()
            if name.startswith("nqnfcnci") or name.startswith("nfc_st"):
                has_nfc_override = True
                break

        if has_nfc_override:
            self.logger.info(
                "Detected NFC override, cleaning old NFC directories in target..."
            )
            for p in self.ctx.target_dir.rglob("*"):
                if p.is_dir():
                    name = p.name.lower()
                    if name.startswith("nqnfcnci") or name.startswith("nfc_st"):
                        self.logger.info(f"Removing old NFC dir: {p}")
                        shutil.rmtree(p)

        self.logger.info("Copying override files...")
        try:
            shutil.copytree(override_src, self.ctx.target_dir, dirs_exist_ok=True)
        except Exception as e:
            self.logger.error(f"Failed to copy overrides: {e}")

    def _fix_vintf_manifest(self):
        self.logger.info("Checking VINTF manifest for VNDK version...")

        vndk_version = self.ctx.stock.get_prop("ro.vndk.version")
        if not vndk_version:
            vendor_prop = self.ctx.target_dir / "vendor/build.prop"
            if vendor_prop.exists():
                try:
                    content = vendor_prop.read_text(encoding="utf-8", errors="ignore")
                    match = re.search(r"ro\.vndk\.version=(.*)", content)
                    if match:
                        vndk_version = match.group(1).strip()
                except:
                    pass

        if not vndk_version:
            self.logger.warning("Could not determine VNDK version, skipping VINTF fix.")
            return

        self.logger.info(f"Target VNDK Version: {vndk_version}")

        target_xml = self._find_file_recursive(
            self.ctx.target_dir / "system_ext", "manifest.xml"
        )
        if not target_xml:
            self.logger.warning("manifest.xml not found.")
            return

        original_content = target_xml.read_text(encoding="utf-8")

        if f"<version>{vndk_version}</version>" in original_content:
            self.logger.info(
                f"VNDK {vndk_version} already exists in manifest. Skipping."
            )
            return

        new_block = f"""    <vendor-ndk>
        <version>{vndk_version}</version>
    </vendor-ndk>"""

        if "</manifest>" in original_content:
            new_content = original_content.replace(
                "</manifest>", f"{new_block}\n</manifest>"
            )

            target_xml.write_text(new_content, encoding="utf-8")
            self.logger.info(
                f"Injected VNDK {vndk_version} into {target_xml.name} (Text Mode)"
            )
        else:
            self.logger.error("Invalid manifest.xml: No </manifest> tag found.")


class FrameworkModifier:
    def __init__(self, context):
        self.ctx = context
        self.logger = logging.getLogger("FrameworkModifier")
        self.shell = ShellRunner()
        self.bin_dir = Path("bin").resolve()

        self.apktool_path = self.bin_dir / "apktool" / "apktool"
        self.apkeditor_path = self.bin_dir / "apktool" / "APKEditor.jar"
        self.baksmali_path = self.bin_dir / "apktool" / "baksmali.jar"

        self.RETRUN_TRUE = ".locals 1\n    const/4 v0, 0x1\n    return v0"
        self.RETRUN_FALSE = ".locals 1\n    const/4 v0, 0x0\n    return v0"
        self.REMAKE_VOID = ".locals 0\n    return-void"
        self.INVOKE_TRUE = (
            "invoke-static {}, Lcom/android/internal/util/HookHelper;->RETURN_TRUE()Z"
        )
        self.PRELOADS_SHAREDUIDS = ".locals 1\n    invoke-static {}, Lcom/android/internal/util/HookHelper;->RETURN_TRUE()Z\n    move-result v0\n    sput-boolean v0, Lcom/android/server/pm/ReconcilePackageUtils;->ALLOW_NON_PRELOADS_SYSTEM_SHAREDUIDS:Z\n    return-void"

        self.temp_dir = self.ctx.target_dir.parent / "temp_modifier"

        self._file_cache = {}
        self._dir_cache = {}

    def run(self):
        self.logger.info("Starting System Modification...")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            futures.append(executor.submit(self._mod_miui_services))
            futures.append(executor.submit(self._mod_services))
            futures.append(executor.submit(self._mod_framework))

            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self.logger.error(f"Framework modification failed: {e}")

        self._inject_xeu_toolbox()
        self.logger.info("System Modification Completed.")

    def _run_smalikit(self, **kwargs):
        args = SmaliArgs(**kwargs)
        patcher = SmaliKit(args)
        target = args.file_path if args.file_path else args.path
        if target:
            patcher.walk_and_patch(target)

    def _apkeditor_decode(self, jar_path, out_dir):
        self.shell.run_java_jar(
            self.apkeditor_path, ["d", "-f", "-i", str(jar_path), "-o", str(out_dir)]
        )

    def _apkeditor_build(self, src_dir, out_jar):
        self.shell.run_java_jar(
            self.apkeditor_path, ["b", "-f", "-i", str(src_dir), "-o", str(out_jar)]
        )

    def _find_file(self, root, name_pattern):
        for p in Path(root).rglob(name_pattern):
            if p.is_file():
                return p
        return None

    def _replace_text_in_file(self, file_path, old, new):
        if not file_path or not file_path.exists():
            return
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        if old in content:
            new_content = content.replace(old, new)
            file_path.write_text(new_content, encoding="utf-8")
            self.logger.info(
                f"Patched {file_path.name}: {old[:20]}... -> {new[:20]}..."
            )

    def _mod_miui_services(self):
        jar_path = self._find_file(self.ctx.target_dir, "miui-services.jar")
        if not jar_path:
            return

        self.logger.info(f"Modifying {jar_path.name}...")
        work_dir = self.temp_dir / "miui-services"
        self._apkeditor_decode(jar_path, work_dir)

        if getattr(self.ctx, "is_port_eu_rom", False):
            fuc_body = ".locals 1\n    invoke-direct {p0}, Lcom/android/server/SystemServerStub;-><init>()V\n    return-void"
            self._run_smalikit(
                path=str(work_dir),
                iname="SystemServerImpl.smali",
                method="<init>()V",
                remake=fuc_body,
            )

        remake_void = ".locals 0\n    return-void"
        remake_false = ".locals 1\n    const/4 v0, 0x0\n    return v0"

        self._run_smalikit(
            path=str(work_dir),
            iname="PackageManagerServiceImpl.smali",
            method="verifyIsolationViolation",
            remake=remake_void,
            recursive=True,
        )
        self._run_smalikit(
            path=str(work_dir),
            iname="PackageManagerServiceImpl.smali",
            method="canBeUpdate",
            remake=remake_void,
            recursive=True,
        )

        patches = [
            (
                "com/android/server/am/BroadcastQueueModernStubImpl.smali",
                [
                    (
                        "sget-boolean v2, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z",
                        "const/4 v2, 0x1",
                    )
                ],
            ),
            (
                "com/android/server/am/ActivityManagerServiceImpl.smali",
                [
                    (
                        "sget-boolean v1, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z",
                        "const/4 v1, 0x1",
                    ),
                    (
                        "sget-boolean v4, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z",
                        "const/4 v4, 0x1",
                    ),
                ],
            ),
            (
                "com/android/server/am/ProcessManagerService.smali",
                [
                    (
                        "sget-boolean v0, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z",
                        "const/4 v0, 0x1",
                    )
                ],
            ),
            (
                "com/android/server/am/ProcessSceneCleaner.smali",
                [
                    (
                        "sget-boolean v4, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z",
                        "const/4 v0, 0x1",
                    )
                ],
            ),
        ]

        for rel_path, rules in patches:
            target_smali = self._find_file(work_dir, Path(rel_path).name)
            if target_smali:
                for old_str, new_str in rules:
                    self._replace_text_in_file(target_smali, old_str, new_str)

        self._run_smalikit(
            path=str(work_dir),
            iname="WindowManagerServiceImpl.smali",
            method="notAllowCaptureDisplay(Lcom/android/server/wm/RootWindowContainer;I)Z",
            remake=remake_false,
            recursive=True,
        )

        self._apkeditor_build(work_dir, jar_path)

    def _mod_services(self):
        jar_path = self._find_file(self.ctx.target_dir, "services.jar")
        if not jar_path:
            return

        self.logger.info(f"Modifying {jar_path.name}...")
        work_dir = self.temp_dir / "services"
        shutil.copy2(jar_path, self.temp_dir / "services.jar.bak")
        self._apkeditor_decode(jar_path, work_dir)

        remake_void = ".locals 0\n    return-void"
        remake_false = ".locals 1\n    const/4 v0, 0x0\n    return v0"
        remake_true = ".locals 1\n    const/4 v0, 0x1\n    return v0"

        self._run_smalikit(
            path=str(work_dir),
            iname="PackageManagerServiceUtils.smali",
            method="checkDowngrade",
            remake=remake_void,
            recursive=True,
        )
        for m in [
            "matchSignaturesCompat",
            "matchSignaturesRecover",
            "matchSignatureInSystem",
            "verifySignatures",
        ]:
            self._run_smalikit(
                path=str(work_dir),
                iname="PackageManagerServiceUtils.smali",
                method=m,
                remake=remake_false,
            )

        self._run_smalikit(
            path=str(work_dir),
            iname="KeySetManagerService.smali",
            method="checkUpgradeKeySetLocked",
            remake=remake_true,
        )

        self._run_smalikit(
            path=str(work_dir),
            iname="VerifyingSession.smali",
            method="isVerificationEnabled",
            remake=remake_false,
        )

        self._apkeditor_build(work_dir, jar_path)

    def _find_file_recursive(self, root_dir: Path, filename: str) -> Path | None:
        cache_key = (str(root_dir), filename)
        if cache_key in self._file_cache:
            cached_path = self._file_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._file_cache[cache_key]

        if not root_dir.exists():
            return None
        try:
            result = next(root_dir.rglob(filename))
            self._file_cache[cache_key] = result
            return result
        except StopIteration:
            self._file_cache[cache_key] = None
            return None

    def _find_dir_recursive(self, root_dir: Path, dirname: str) -> Path | None:
        cache_key = (str(root_dir), dirname)
        if cache_key in self._dir_cache:
            cached_path = self._dir_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._dir_cache[cache_key]

        if not root_dir.exists():
            return None
        for p in root_dir.rglob(dirname):
            if p.is_dir() and p.name == dirname:
                self._dir_cache[cache_key] = p
                return p
        self._dir_cache[cache_key] = None
        return None

    def _mod_framework(self):
        jar = self._find_file_recursive(self.ctx.target_dir, "framework.jar")
        if not jar:
            return
        self.logger.info(f"Modifying {jar.name} (PropsHook, PIF & SignBypass)...")

        wd = self.temp_dir / "framework"
        self.shell.run_java_jar(
            self.apkeditor_path,
            ["d", "-f", "-i", str(jar), "-o", str(wd), "-no-dex-debug"],
        )

        props_hook_zip = Path("devices/common/PropsHook.zip")
        if self.ctx.assets.ensure_asset(props_hook_zip):
            self.logger.info("Injecting PropsHook...")
            hook_tmp = self.temp_dir / "PropsHook"
            with zipfile.ZipFile(props_hook_zip, "r") as z:
                z.extractall(hook_tmp)

            classes_dex = hook_tmp / "classes.dex"
            if classes_dex.exists():
                classes_out = hook_tmp / "classes"
                self.shell.run_java_jar(
                    self.baksmali_path, ["d", str(classes_dex), "-o", str(classes_out)]
                )

                self._copy_to_next_classes(wd, classes_out)

        self.logger.info("Applying Signature Bypass Patches...")

        self._run_smalikit(
            path=str(wd),
            iname="StrictJarVerifier.smali",
            method="verifyMessageDigest([B[B)Z",
            remake=self.RETRUN_TRUE,
        )
        self._run_smalikit(
            path=str(wd),
            iname="StrictJarVerifier.smali",
            method="<init>(Ljava/lang/String;Landroid/util/jar/StrictJarManifest;Ljava/util/HashMap;Z)V",
            before_line=[
                "iput-boolean p4, p0, Landroid/util/jar/StrictJarVerifier;->signatureSchemeRollbackProtectionsEnforced:Z",
                "const/4 p4, 0x0",
            ],
        )

        targets = [
            ("ApkSigningBlockUtils.smali", "verifyIntegrityFor1MbChunkBasedAlgorithm"),
            ("ApkSigningBlockUtils.smali", "verifyProofOfRotationStruct"),
            ("ApkSignatureSchemeV2Verifier.smali", "verifySigner"),
            ("ApkSignatureSchemeV3Verifier.smali", "verifySigner"),
            ("ApkSignatureSchemeV4Verifier.smali", "verifySigner"),
        ]
        s1 = "Ljava/security/MessageDigest;->isEqual([B[B)Z"
        s2 = "Ljava/security/Signature;->verify([B)Z"

        for smali_file, method in targets:
            self._run_smalikit(
                path=str(wd),
                iname=smali_file,
                method=method,
                after_line=[s1, self.INVOKE_TRUE],
                recursive=True,
            )
            self._run_smalikit(
                path=str(wd),
                iname=smali_file,
                method=method,
                after_line=[s2, self.INVOKE_TRUE],
                recursive=True,
            )

        for m in [
            "checkCapability",
            "checkCapabilityRecover",
            "hasCommonAncestor",
            "signaturesMatchExactly",
        ]:
            self._run_smalikit(
                path=str(wd),
                iname="PackageParser$SigningDetails.smali",
                method=m,
                remake=self.RETRUN_TRUE,
                recursive=True,
            )
            self._run_smalikit(
                path=str(wd),
                iname="SigningDetails.smali",
                method=m,
                remake=self.RETRUN_TRUE,
                recursive=True,
            )

        self._run_smalikit(
            path=str(wd),
            iname="AssetManager.smali",
            method="containsAllocatedTable",
            remake=self.RETRUN_FALSE,
        )

        self._run_smalikit(
            path=str(wd),
            iname="StrictJarFile.smali",
            method="<init>(Ljava/lang/String;Ljava/io/FileDescriptor;ZZ)V",
            after_line=["move-result-object v6", "const/4 v6, 0x1"],
        )

        self._run_smalikit(
            path=str(wd),
            iname="ApkSignatureVerifier.smali",
            method="getMinimumSignatureSchemeVersionForTargetSdk",
            remake=self.RETRUN_TRUE,
        )

        pif_zip = Path("devices/common/pif_patch.zip")
        if self.ctx.assets.ensure_asset(pif_zip):
            self._apply_pif_patch(wd, pif_zip)
        else:
            self.logger.warning("pif_patch.zip not found, skipping PIF injection.")

        target_file = self._find_file_recursive(wd, "PendingIntent.smali")
        if target_file:
            hook_code = "\n    # [AutoCopy Hook]\n    invoke-static {p0, p2}, Lcom/android/internal/util/HookHelper;->onPendingIntentGetActivity(Landroid/content/Context;Landroid/content/Intent;)V"
            self._run_smalikit(
                file_path=str(target_file),
                method="getActivity(Landroid/content/Context;ILandroid/content/Intent;I)",
                insert_line=["2", hook_code],
            )
            self._run_smalikit(
                file_path=str(target_file),
                method="getActivity(Landroid/content/Context;ILandroid/content/Intent;ILandroid/os/Bundle;)",
                insert_line=["2", hook_code],
            )

        self._integrate_custom_platform_key(wd)

        # ==========================================
        # 6. 注入 HookHelper 实现 (AutoCopy)
        # ==========================================
        self._inject_hook_helper_methods(wd)

        self._apkeditor_build(wd, jar)

    def _inject_hook_helper_methods(self, work_dir):
        """
        注入 HookHelper 的额外方法 (AutoCopy 等)
        """
        hook_helper = self._find_file_recursive(work_dir, "HookHelper.smali")
        if not hook_helper:
            self.logger.warning("HookHelper.smali not found, creating new one...")
            return

        self.logger.info(f"Injecting implementation into {hook_helper.name}...")

        # 定义 Smali 代码
        smali_code = r"""
.method public static onPendingIntentGetActivity(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 5

    .line 100
    if-eqz p1, :cond_end

    # Check for extras
    invoke-virtual {p1}, Landroid/content/Intent;->getExtras()Landroid/os/Bundle;
    move-result-object v0
    if-nez v0, :cond_check_clip

    goto :cond_end

    :cond_check_clip
    # Try to find "sms_body" or typical keys
    const-string v1, "android.intent.extra.TEXT"
    invoke-virtual {v0, v1}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    
    if-nez v1, :cond_check_body
    const-string v1, "sms_body"
    invoke-virtual {v0, v1}, Landroid/os/Bundle;->getString(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    :cond_check_body
    if-nez v1, :cond_scan_match
    goto :cond_end

    :cond_scan_match
    # Now v1 is the content string. Run Regex.
    # Regex: (?<![0-9])([0-9]{4,6})(?![0-9])
    
    const-string v2, "(?<![0-9])([0-9]{4,6})(?![0-9])"
    invoke-static {v2}, Ljava/util/regex/Pattern;->compile(Ljava/lang/String;)Ljava/util/regex/Pattern;
    move-result-object v2
    invoke-virtual {v2, v1}, Ljava/util/regex/Pattern;->matcher(Ljava/lang/CharSequence;)Ljava/util/regex/Matcher;
    move-result-object v2
    
    invoke-virtual {v2}, Ljava/util/regex/Matcher;->find()Z
    move-result v3
    if-eqz v3, :cond_end
    
    # Found match! Group 1 is the code
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Ljava/util/regex/Matcher;->group(I)Ljava/lang/String;
    move-result-object v2
    
    if-eqz v2, :cond_end
    
    # Copy to Clipboard
    const-string v3, "clipboard"
    invoke-virtual {p0, v3}, Landroid/content/Context;->getSystemService(Ljava/lang/String;)Ljava/lang/Object;
    move-result-object v3
    check-cast v3, Landroid/content/ClipboardManager;
    
    if-eqz v3, :cond_end
    
    # ClipData.newPlainText("Verification Code", code)
    const-string v4, "Verification Code"
    invoke-static {v4, v2}, Landroid/content/ClipData;->newPlainText(Ljava/lang/CharSequence;Ljava/lang/CharSequence;)Landroid/content/ClipData;
    move-result-object v2
    
    invoke-virtual {v3, v2}, Landroid/content/ClipboardManager;->setPrimaryClip(Landroid/content/ClipData;)V
    
    :cond_end
    return-void
.end method
"""
        # Append method to HookHelper.smali
        content = hook_helper.read_text(encoding="utf-8")
        if "onPendingIntentGetActivity" not in content:
            with open(hook_helper, "a", encoding="utf-8") as f:
                f.write(smali_code)

            self.logger.info("Added onPendingIntentGetActivity to HookHelper.")
        else:
            self.logger.info("onPendingIntentGetActivity already exists.")

    # --------------------------------------------------------------------------
    # PIF Patch 逻辑 (模拟 patches.sh)
    # --------------------------------------------------------------------------
    def _apply_pif_patch(self, work_dir, pif_zip):
        self.logger.info("Applying PIF Patch (Instrumentation, KeyStoreSpi, AppPM)...")

        temp_pif = self.temp_dir / "pif_classes"
        with zipfile.ZipFile(pif_zip, "r") as z:
            z.extractall(temp_pif)
        self._copy_to_next_classes(work_dir, temp_pif / "classes")

        self.logger.info(f"Merging files from {temp_pif} to {self.ctx.target_dir}...")

        for item in temp_pif.iterdir():
            if item.name == "classes":
                continue

            target_path = self.ctx.target_dir / item.name

            self.logger.info(f"  Merging: {item.name} -> {target_path}")

            if item.is_dir():
                shutil.copytree(item, target_path, symlinks=True, dirs_exist_ok=True)
            else:
                if target_path.exists() or os.path.islink(target_path):
                    if target_path.is_dir():
                        shutil.rmtree(target_path)
                    else:
                        os.unlink(target_path)

                shutil.copy2(item, target_path, follow_symlinks=False)

        inst_smali = self._find_file_recursive(work_dir, "Instrumentation.smali")
        if inst_smali:
            content = inst_smali.read_text(encoding="utf-8", errors="ignore")

            method1 = "newApplication(Ljava/lang/ClassLoader;Ljava/lang/String;Landroid/content/Context;)Landroid/app/Application;"
            if method1 in content:
                reg = self._extract_register_from_invoke(
                    content,
                    method1,
                    "Landroid/app/Application;->attach(Landroid/content/Context;)V",
                    arg_index=1,
                )
                if reg:
                    patch_code = f"    invoke-static {{{reg}}}, Lcom/android/internal/util/PropsHookUtils;->setProps(Landroid/content/Context;)V\n    invoke-static {{{reg}}}, Lcom/android/internal/util/danda/OemPorts10TUtils;->onNewApplication(Landroid/content/Context;)V"
                    self._run_smalikit(
                        file_path=str(inst_smali),
                        method=method1,
                        before_line=["return-object", patch_code],
                    )

            method2 = "newApplication(Ljava/lang/Class;Landroid/content/Context;)Landroid/app/Application;"
            if method2 in content:
                reg = self._extract_register_from_invoke(
                    content,
                    method2,
                    "Landroid/app/Application;->attach(Landroid/content/Context;)V",
                    arg_index=1,
                )
                if reg:
                    patch_code = f"    invoke-static {{{reg}}}, Lcom/android/internal/util/PropsHookUtils;->setProps(Landroid/content/Context;)V\n    invoke-static {{{reg}}}, Lcom/android/internal/util/danda/OemPorts10TUtils;->onNewApplication(Landroid/content/Context;)V"
                    self._run_smalikit(
                        file_path=str(inst_smali),
                        method=method2,
                        before_line=["return-object", patch_code],
                    )

        keystore_smali = self._find_file_recursive(work_dir, "AndroidKeyStoreSpi.smali")
        if keystore_smali:
            self._run_smalikit(
                file_path=str(keystore_smali),
                method="engineGetCertificateChain",
                insert_line=[
                    "2",
                    "    invoke-static {}, Lcom/android/internal/util/danda/OemPorts10TUtils;->onEngineGetCertificateChain()V",
                ],
            )

            content = keystore_smali.read_text(encoding="utf-8")
            aput_matches = list(
                re.finditer(
                    r"aput-object\s+([vp]\d+),\s+([vp]\d+),\s+([vp]\d+)", content
                )
            )
            if aput_matches:
                pattern = re.compile(
                    r"(\.method.+engineGetCertificateChain.+?\.end method)", re.DOTALL
                )
                match = pattern.search(content)
                if match:
                    body = match.group(1)
                    inner_aputs = list(
                        re.finditer(
                            r"aput-object\s+([vp]\d+),\s+([vp]\d+),\s+([vp]\d+)", body
                        )
                    )
                    if inner_aputs:
                        last_aput = inner_aputs[-1]
                        array_reg = last_aput.group(2)

                        spoof_code = f"\n    invoke-static {{{array_reg}}}, Lcom/android/internal/util/danda/OemPorts10TUtils;->genCertificateChain([Ljava/security/cert/Certificate;)[Ljava/security/cert/Certificate;\n    move-result-object {array_reg}\n"

                        old_line = last_aput.group(0)
                        new_body = body.replace(old_line, old_line + spoof_code)
                        content = content.replace(body, new_body)
                        keystore_smali.write_text(content, encoding="utf-8")

        app_pm_smali = self._find_file_recursive(
            work_dir, "ApplicationPackageManager.smali"
        )
        if app_pm_smali:
            self.logger.info("Hooking ApplicationPackageManager...")

            method_sig = "hasSystemFeature(Ljava/lang/String;I)Z"

            repl_pattern = (
                r"invoke-static {p1, \1}, Lcom/android/internal/util/PropsHookUtils;->hasSystemFeature(Ljava/lang/String;Z)Z"
                r"\n    move-result \1"
                r"\n    return \1"
            )

            self._run_smalikit(
                file_path=str(app_pm_smali),
                method=method_sig,
                regex_replace=(r"return\s+([vp]\d+)", repl_pattern),
            )

        policy_tool = self.bin_dir / "insert_selinux_policy.py"
        config_json = Path("devices/common/pif_updater_policy.json")
        cil_path = self.ctx.target_dir / "system/system/etc/selinux/plat_sepolicy.cil"

        if policy_tool.exists() and config_json.exists() and cil_path.exists():
            self.shell.run(
                [
                    "python3",
                    str(policy_tool),
                    "--config",
                    str(config_json),
                    str(cil_path),
                ]
            )

            fc_path = (
                self.ctx.target_dir / "system/system/etc/selinux/plat_file_contexts"
            )
            if fc_path.exists():
                with open(fc_path, "a") as f:
                    f.write(
                        "\n/system/bin/pif-updater       u:object_r:pif_updater_exec:s0\n"
                    )
                    f.write("/data/system/pif_tmp.apk  u:object_r:pif_data_file:s0\n")
                    f.write("/data/PIF.apk u:object_r:pif_data_file:s0\n")
                    f.write("/data/local/tmp/PIF.apk   u:object_r:pif_data_file:s0\n")

        # Properties migrated to devices/common/features.json

    # --------------------------------------------------------------------------
    # 自定义平台签名校验逻辑
    # --------------------------------------------------------------------------
    def _integrate_custom_platform_key(self, work_dir):
        epm_smali = self._find_file_recursive(work_dir, "ExtraPackageManager.smali")
        if not epm_smali:
            return
        self.logger.info("Injecting Custom Platform Key Check...")

        MY_PLATFORM_KEY = "308203bb308202a3a00302010202146a0b4f6a1a8f61a32d8450ead92d479dea486573300d06092a864886f70d01010b0500306c310b300906035504061302434e3110300e06035504080c075369436875616e3110300e06035504070c074368656e6744753110300e060355040a0c07504f5254524f4d31133011060355040b0c0a4d61696e7461696e65723112301006035504030c09427275636554656e673020170d3236303230323031333632385a180f32303533303632303031333632385a306c310b300906035504061302434e3110300e06035504080c075369436875616e3110300e06035504070c074368656e6744753110300e060355040a0c07504f5254524f4d31133011060355040b0c0a4d61696e7461696e65723112301006035504030c09427275636554656e6730820122300d06092a864886f70d01010105000382010f003082010a0282010100cb68bcf8927a175624a0a7428f1bbd67b4cf18c8ba42b73de9649fd2aa42935b9195b27ccd611971056654db51499ffa01783a1dbc95e03f9c557d4930193c3d04f9016a84411b502ea844fac9d463b4c9eed2d73ca3267b8a399f5da254941c7413d2a7534fd30a4ed10567933bfda249e2027ce74da667de3b6278844d232e038c2c98deb7d172a44b2fd9ec90ea74cb1c96b647044c60ce18cec93b60b84065ddd8800e10bcf465e4f3ace6d423ef2b235d75081e36b5d0f1ca858090d3dd8d74437ebb504490a8e7e9e3e2b696c3ac8e2ec856bedf4efe4e05e14f2437f81fbc8428aa330cdde0816450b4416e10f743204c17ee65b92ebc61799b4cf42b0203010001a3533051301d0603551d0e041604140a318d86cc0040341341b6dc716094da06cd4dd6301f0603551d230418301680140a318d86cc0040341341b6dc716094da06cd4dd6300f0603551d130101ff040530030101ff300d06092a864886f70d01010b0500038201010023e7aeda5403f40c794504e3edf99182a5eb53c9ddec0d93fd9fe6539e1520ea6ad08ac3215555f3fe366fa6ab01e0f45d6ce1512416c572f387a72408dde6442b76e405296cc8c128844fe68a29f6a114eb6f303e3545ea0b32d85e9c7d45cfa3c860b03d00171bb2aa4434892bf484dd390643f324a2e38a5e6ce7f26e92b3d02ac8605514b9c75a8aab9ab990c01951213f7214a36389c0759cfb68737bb3bb85dff4b1b40377279e2c82298351c276ab266869d6494b838bd6cc175185f705b8806eb1950becec57fb4f9b50240bb92d1d30bbb5764d311d18446588e5fd2b9785c635f2bb690df1e4fb595305371350c6d306d3f6cae3bc4974e9d8609c"

        hook_code = f"""
    # [Start] Custom Platform Key Check
    const/4 v2, 0x1
    new-array v2, v2, [Landroid/content/pm/Signature;
    new-instance v3, Landroid/content/pm/Signature;
    const-string v4, "{MY_PLATFORM_KEY}"
    invoke-direct {{v3, v4}}, Landroid/content/pm/Signature;-><init>(Ljava/lang/String;)V
    const/4 v4, 0x0
    aput-object v3, v2, v4
    invoke-static {{p0, v2}}, Lmiui/content/pm/ExtraPackageManager;->compareSignatures([Landroid/content/pm/Signature;[Landroid/content/pm/Signature;)I
    move-result v2
    if-eqz v2, :cond_custom_skip
    const/4 v2, 0x1
    return v2
    :cond_custom_skip
    # [End]"""

        self._run_smalikit(
            file_path=str(epm_smali),
            method="isTrustedPlatformSignature([Landroid/content/pm/Signature;)Z",
            regex_replace=(r"\.locals\s+\d+", ".locals 5"),
        )

        self._run_smalikit(
            file_path=str(epm_smali),
            method="isTrustedPlatformSignature([Landroid/content/pm/Signature;)Z",
            insert_line=["2", hook_code],
        )

    def _copy_to_next_classes(self, work_dir, source_dir):
        max_num = 1
        for d in work_dir.glob("smali/classes*"):
            name = d.name
            if name == "classes":
                num = 1
            else:
                try:
                    num = int(name.replace("classes", ""))
                except:
                    num = 1
            if num > max_num:
                max_num = num

        target = work_dir / "smali" / f"classes{max_num + 1}"
        shutil.copytree(source_dir, target, dirs_exist_ok=True)
        self.logger.info(f"Copied classes to {target.name}")

    def _extract_register_from_invoke(
        self,
        content: str,
        method_signature: str,
        invoke_signature: str,
        arg_index: int = 1,
    ) -> str | None:
        method_pattern = re.compile(
            rf"\.method[^\n]*?{re.escape(method_signature)}(.*?)\.end method", re.DOTALL
        )
        method_match = method_pattern.search(content)

        if not method_match:
            self.logger.warning(f"Target method not found: {method_signature}")
            return None

        method_body = method_match.group(1)

        invoke_pattern = re.compile(
            rf"invoke-\w+\s+{{(.*?)}},\s+{re.escape(invoke_signature)}"
        )
        invoke_match = invoke_pattern.search(method_body)

        if not invoke_match:
            self.logger.warning(
                f"Invoke signature not found in method body: {invoke_signature}"
            )
            return None

        matched_regs_str = invoke_match.group(1)

        reg_list = [r.strip() for r in matched_regs_str.split(",") if r.strip()]

        if arg_index < len(reg_list):
            extracted_reg = reg_list[arg_index]
            self.logger.debug(
                f"Extracted register {extracted_reg} from {method_signature}"
            )
            return extracted_reg
        else:
            self.logger.warning(
                f"arg_index {arg_index} out of bounds for registers: {reg_list}"
            )
            return None

    def _inject_xeu_toolbox(self):
        xeu_zip = Path("devices/common/xeutoolbox.zip")
        if not self.ctx.assets.ensure_asset(xeu_zip):
            return

        self.logger.info("Injecting Xiaomi.eu Toolbox...")

        try:
            with zipfile.ZipFile(xeu_zip, "r") as z:
                z.extractall(self.ctx.target_dir)
            self.logger.info(f"Extracted {xeu_zip.name}")
        except Exception as e:
            self.logger.error(f"Failed to extract xeutoolbox: {e}")
            return

        target_files = [
            self.ctx.target_dir / "config/system_ext_file_contexts",
            self.ctx.target_dir / "system_ext/etc/selinux/system_ext_file_contexts",
        ]

        context_line = "\n/system_ext/xbin/xeu_toolbox  u:object_r:toolbox_exec:s0\n"

        for f in target_files:
            if f.exists():
                try:
                    with open(f, "a", encoding="utf-8") as file:
                        file.write(context_line)
                    self.logger.info(f"Updated contexts: {f.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to append context to {f}: {e}")

        cil_file = (
            self.ctx.target_dir / "system_ext/etc/selinux/system_ext_sepolicy.cil"
        )
        policy_line = "\n(allow init toolbox_exec (file ((execute_no_trans))))\n"

        if cil_file.exists():
            try:
                with open(cil_file, "a", encoding="utf-8") as f:
                    f.write(policy_line)
                self.logger.info(f"Updated sepolicy: {cil_file.name}")
            except Exception as e:
                self.logger.warning(f"Failed to append policy to {cil_file}: {e}")


class FirmwareModifier:
    def __init__(self, context):
        self.ctx = context
        self.logger = logging.getLogger("FirmwareMod")
        self.shell = ShellRunner()
        self.bin_dir = Path("bin").resolve()

        if not self.ctx.tools.magiskboot.exists():
            self.logger.error(
                f"magiskboot binary not found at {self.ctx.tools.magiskboot}"
            )
            return

        self.assets_dir = self.bin_dir.parent / "assets"
        self.ksu_version_file = self.assets_dir / "ksu_version.txt"
        self.repo_owner = "tiann"
        self.repo_name = "KernelSU"

    def run(self):
        self.logger.info("Starting Firmware Modification...")

        if getattr(self.ctx, "disable_vbmeta", False):
            self._patch_vbmeta()

        if getattr(self.ctx, "enable_ksu", False):
            if getattr(self.ctx, "ksu_type", "gki") == "gki":
                self._patch_ksu()
            else:
                self._patch_non_gki_kernel()

        self.logger.info("Firmware Modification Completed.")

    def _patch_vbmeta(self):
        self.logger.info("Patching vbmeta images (Disabling AVB)...")

        repack_images_dir = self.ctx.work_dir / "repack_images"
        vbmeta_images = list(repack_images_dir.glob("vbmeta*.img"))
        vbmeta_images.extend(list(self.ctx.target_dir.rglob("vbmeta*.img")))

        if not vbmeta_images:
            self.logger.warning("No vbmeta images found in target directory.")
            return

        AVB_MAGIC = b"AVB0"
        FLAGS_OFFSET = 123
        FLAGS_TO_SET = b"\x03"

        for img_path in vbmeta_images:
            try:
                with open(img_path, "r+b") as f:
                    magic = f.read(4)
                    if magic != AVB_MAGIC:
                        self.logger.warning(
                            f"Skipping {img_path.name}: Invalid AVB Magic"
                        )
                        continue

                    f.seek(FLAGS_OFFSET)
                    f.write(FLAGS_TO_SET)
                    self.logger.info(f"Successfully patched: {img_path.name}")

            except Exception as e:
                self.logger.error(f"Failed to patch {img_path.name}: {e}")

    def _patch_ksu(self):
        self.logger.info("Attempting to patch KernelSU...")

        target_init_boot = self.ctx.repack_images_dir / "init_boot.img"
        target_boot = self.ctx.repack_images_dir / "boot.img"

        if not target_init_boot.exists():
            self.logger.warning("init_boot.img not found, skipping KSU patch.")
            return
        if not target_boot.exists():
            self.logger.warning(
                "boot.img not found (needed for KMI check), skipping KSU patch."
            )
            return

        if not self.ctx.tools.magiskboot or not self.ctx.tools.magiskboot.exists():
            self.logger.error("magiskboot binary not found!")
            return

        kmi_version = self._analyze_kmi(target_boot)
        if not kmi_version:
            self.logger.error("Failed to determine KMI version.")
            return

        self.logger.info(f"Detected KMI Version: {kmi_version}")

        if not self._prepare_ksu_assets(kmi_version):
            self.logger.error("Failed to prepare KSU assets.")
            return

        self._apply_ksu_patch(target_init_boot, kmi_version)

    def _patch_non_gki_kernel(self):
        self.logger.info("Integrating non-GKI custom kernel (AnyKernel)...")
        device_code = getattr(self.ctx, "device_code", "unknown")
        device_dir = Path(f"devices/{device_code}")
        if not device_dir.exists():
            device_dir = Path(f"devices/target/{device_code}")

        if not device_dir.exists():
            self.logger.warning(
                f"Device directory not found for {device_code}, skipping kernel patch."
            )
            return

        # Find kernel zip (KSU or NoKSU)
        ksu_zips = list(device_dir.glob("*-KSU*.zip"))
        noksu_zips = list(device_dir.glob("*-NoKSU*.zip"))

        target_zip = None
        if ksu_zips:
            target_zip = ksu_zips[0]
            self.logger.info(f"Found KSU kernel zip: {target_zip.name}")
        elif noksu_zips:
            target_zip = noksu_zips[0]
            self.logger.info(f"Found NoKSU kernel zip: {target_zip.name}")

        if not target_zip:
            self.logger.warning("No custom kernel zip found in device directory.")
            return

        target_boot = self.ctx.work_dir / "repack_images" / "boot.img"
        if not target_boot.exists():
            self.logger.error("boot.img not found in repack_images.")
            return

        with tempfile.TemporaryDirectory(prefix="anykernel_") as tmp:
            tmp_path = Path(tmp)
            ak_path = tmp_path / "anykernel"
            ak_path.mkdir()

            with zipfile.ZipFile(target_zip, "r") as zip_ref:
                zip_ref.extractall(ak_path)

            # Find kernel, dtb, dtbo
            kernel_file = next(
                (
                    f
                    for f in ak_path.glob("*")
                    if f.name.lower()
                    in [
                        "image",
                        "zimage",
                        "kernel",
                        "image.gz",
                        "image.lz4",
                        "boot.img",
                    ]
                ),
                None,
            )
            dtb_file = next(
                (
                    f
                    for f in ak_path.glob("*")
                    if f.name.lower() in ["dtb", "dtb.img"]
                    or f.suffix.lower() == ".dtb"
                ),
                None,
            )
            dtbo_file = next((f for f in ak_path.glob("dtbo.img")), None)

            if not kernel_file:
                self.logger.error("No kernel image found in zip.")
                return

            boot_tmp = tmp_path / "boot"
            boot_tmp.mkdir()
            shutil.copy(target_boot, boot_tmp / "boot.img")

            self.shell.run(
                [str(self.ctx.tools.magiskboot), "unpack", "-h", "boot.img"],
                cwd=boot_tmp,
            )

            # Replace kernel
            if kernel_file.name == "boot.img":
                inner_tmp = tmp_path / "inner"
                inner_tmp.mkdir()
                shutil.copy(kernel_file, inner_tmp / "boot.img")
                self.shell.run(
                    [str(self.ctx.tools.magiskboot), "unpack", "-h", "boot.img"],
                    cwd=inner_tmp,
                )
                if (inner_tmp / "kernel").exists():
                    shutil.copy(inner_tmp / "kernel", boot_tmp / "kernel")
                if (inner_tmp / "dtb").exists():
                    shutil.copy(inner_tmp / "dtb", boot_tmp / "dtb")
            else:
                if kernel_file.suffix.lower() == ".gz":
                    import gzip

                    with (
                        gzip.open(kernel_file, "rb") as f_in,
                        open(boot_tmp / "kernel", "wb") as f_out,
                    ):
                        shutil.copyfileobj(f_in, f_out)
                elif kernel_file.suffix.lower() == ".lz4":
                    self.shell.run(
                        ["lz4", "-d", str(kernel_file), str(boot_tmp / "kernel")]
                    )
                else:
                    shutil.copy(kernel_file, boot_tmp / "kernel")

            if dtb_file:
                shutil.copy(dtb_file, boot_tmp / "dtb")

            self.shell.run(
                [str(self.ctx.tools.magiskboot), "repack", "boot.img", "boot_new.img"],
                cwd=boot_tmp,
            )

            if (boot_tmp / "boot_new.img").exists():
                shutil.move(boot_tmp / "boot_new.img", target_boot)
                self.logger.info("Custom kernel integrated successfully into boot.img")
            else:
                self.logger.error("Failed to repack boot.img with custom kernel.")

            if dtbo_file:
                target_dtbo = self.ctx.work_dir / "repack_images" / "dtbo.img"
                shutil.copy(dtbo_file, target_dtbo)
                self.logger.info("Custom dtbo.img integrated.")

    def _analyze_kmi(self, boot_img):
        with tempfile.TemporaryDirectory(prefix="ksu_kmi_") as tmp:
            tmp_path = Path(tmp)
            shutil.copy(boot_img, tmp_path / "boot.img")

            try:
                self.shell.run(
                    [str(self.ctx.tools.magiskboot), "unpack", "boot.img"], cwd=tmp_path
                )
            except Exception:
                return None

            kernel_file = tmp_path / "kernel"
            if not kernel_file.exists():
                return None

            try:
                with open(kernel_file, "rb") as f:
                    content = f.read()

                strings = []
                current = []
                for b in content:
                    if 32 <= b <= 126:
                        current.append(chr(b))
                    else:
                        if len(current) >= 4:
                            strings.append("".join(current))
                        current = []

                pattern = re.compile(r"(?:^|\s)(\d+\.\d+)\S*(android\d+)")
                for s in strings:
                    if "Linux version" in s or "android" in s:
                        match = pattern.search(s)
                        if match:
                            return f"{match.group(2)}-{match.group(1)}"
            except Exception:
                pass
        return None

    def _prepare_ksu_assets(self, kmi_version):
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        target_ko = self.assets_dir / f"{kmi_version}_kernelsu.ko"
        target_init = self.assets_dir / "ksuinit"

        if target_ko.exists() and target_init.exists():
            return True

        self.logger.info("Downloading KernelSU assets...")
        try:
            api_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
            with urllib.request.urlopen(api_url, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            assets = data.get("assets", [])

            for asset in assets:
                name = asset["name"]
                url = asset["browser_download_url"]

                if name == "ksuinit" and not target_init.exists():
                    self._download_file(url, target_init)
                elif name == f"{kmi_version}_kernelsu.ko" and not target_ko.exists():
                    self._download_file(url, target_ko)

            return target_ko.exists() and target_init.exists()

        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def _download_file(self, url, dest):
        self.logger.info(f"Downloading {dest.name}...")
        with urllib.request.urlopen(url) as remote, open(dest, "wb") as local:
            shutil.copyfileobj(remote, local)

    def _apply_ksu_patch(self, init_boot_img, kmi_version):
        self.logger.info(f"Patching {init_boot_img.name} with KernelSU...")

        ko_file = self.assets_dir / f"{kmi_version}_kernelsu.ko"
        init_file = self.assets_dir / "ksuinit"

        with tempfile.TemporaryDirectory(prefix="ksu_patch_") as tmp:
            tmp_path = Path(tmp)
            shutil.copy(init_boot_img, tmp_path / "init_boot.img")

            self.shell.run(
                [str(self.ctx.tools.magiskboot), "unpack", "init_boot.img"],
                cwd=tmp_path,
            )

            ramdisk = tmp_path / "ramdisk.cpio"
            if not ramdisk.exists():
                self.logger.error("ramdisk.cpio not found")
                return

            self.shell.run(
                [
                    str(self.ctx.tools.magiskboot),
                    "cpio",
                    "ramdisk.cpio",
                    "mv init init.real",
                ],
                cwd=tmp_path,
            )

            shutil.copy(init_file, tmp_path / "init")
            self.shell.run(
                [
                    str(self.ctx.tools.magiskboot),
                    "cpio",
                    "ramdisk.cpio",
                    "add 0755 init init",
                ],
                cwd=tmp_path,
            )

            shutil.copy(ko_file, tmp_path / "kernelsu.ko")
            self.shell.run(
                [
                    str(self.ctx.tools.magiskboot),
                    "cpio",
                    "ramdisk.cpio",
                    "add 0755 kernelsu.ko kernelsu.ko",
                ],
                cwd=tmp_path,
            )

            self.shell.run(
                [str(self.ctx.tools.magiskboot), "repack", "init_boot.img"],
                cwd=tmp_path,
            )

            new_img = tmp_path / "new-boot.img"
            if new_img.exists():
                shutil.move(new_img, init_boot_img)
                self.logger.info("KernelSU injected successfully.")
            else:
                self.logger.error("Failed to repack init_boot.img")
