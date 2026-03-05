import logging
import re
from pathlib import Path
from typing import Callable, Union, Match
from src.core.context import Context

logger = logging.getLogger(__name__)


class PropertyModifier:
    def __init__(self, context: Context):
        self.ctx = context
        self.target_dir = self.ctx.target_dir

    def run(self):
        logger.info("Starting Property Modification...")

        # 1. Fetch ROM Info (populates context with properties)
        self.ctx.fetch_rom_info()

        # 2. Reconstruct my_product props (New Logic)
        self._reconstruct_my_product_props()

        # 3. Modify build.prop files
        self._modify_build_props()

    def _reconstruct_my_product_props(self):
        """
        Reconstructs my_product/build.prop by using baserom as base
        and moving portrom-specific props to etc/bruce/build.prop.
        Matches the logic from prepare_base_prop and add_prop_from_port.
        """
        target_my_product = self.target_dir / "my_product"
        if not target_my_product.exists():
            return

        logger.info("Reconstructing my_product properties (Base-led strategy)...")

        # 1. Paths
        base_prop_file = self.ctx.baserom.extracted_dir / "my_product" / "build.prop"
        if not base_prop_file.exists():
            base_prop_file = (
                self.ctx.baserom.extracted_dir / "my_product" / "etc" / "build.prop"
            )

        port_prop_file = self.ctx.portrom.extracted_dir / "my_product" / "build.prop"
        if not port_prop_file.exists():
            port_prop_file = (
                self.ctx.portrom.extracted_dir / "my_product" / "etc" / "build.prop"
            )

        target_prop_main = target_my_product / "build.prop"
        target_prop_bruce = target_my_product / "etc" / "bruce" / "build.prop"

        # 2. Force Keys (from Port)
        force_keys = [
            "ro.build.version.oplusrom",
            "ro.build.version.oplusrom.display",
            "ro.build.version.oplusrom.confidential",
            "ro.build.version.realmeui",
        ]

        # 3. Parse Props
        base_props = self._read_prop_to_dict(base_prop_file)
        port_props = self._read_prop_to_dict(port_prop_file)

        # 4. Calculate Bruce Props (Port-only props + Force keys)
        bruce_props = {}
        for key, value in port_props.items():
            if key in force_keys or key not in base_props:
                bruce_props[key] = value
                logger.debug(f"Adding to bruce.prop: {key}={value}")

        # 5. Overwrite target main prop with Base content
        import shutil

        if base_prop_file.exists():
            shutil.copy2(base_prop_file, target_prop_main)

        # 6. Ensure Import statement in main prop
        import_line = "import /mnt/vendor/my_product/etc/bruce/build.prop"
        content = target_prop_main.read_text(encoding="utf-8", errors="ignore")
        if import_line not in content:
            with open(target_prop_main, "a", encoding="utf-8") as f:
                f.write(f"\n\n# Bruce Property Patch\n{import_line}\n")

        # 7. Write Bruce Props
        target_prop_bruce.parent.mkdir(parents=True, exist_ok=True)
        with open(target_prop_bruce, "w", encoding="utf-8") as f:
            f.write("# Properties added from Port ROM\n")
            for key in sorted(bruce_props.keys()):
                f.write(f"{key}={bruce_props[key]}\n")

        logger.info(
            f"Reconstruction complete. {len(bruce_props)} props moved to bruce/build.prop"
        )

    def _read_prop_to_dict(self, file_path: Path) -> dict:
        props = {}
        if not file_path.exists():
            return props
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    props[key.strip()] = val.strip()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
        return props

    def _modify_build_props(self):
        """Main build.prop modification - port.sh lines 1340-1600"""
        self._modify_all_build_props()
        self._modify_my_product_props()
        self._modify_system_ext_props()
        logger.info("Build.prop modifications complete.")

    def _modify_all_build_props(self):
        """Modify all build.prop files - port.sh lines 1345-1376"""
        portrom = self.ctx.portrom

        # Find all build.prop files in portrom extracted_dir
        for build_prop in portrom.extracted_dir.rglob("build.prop"):
            if "system_dlkm" in str(build_prop) or "odm_dlkm" in str(build_prop):
                continue

            content = build_prop.read_text(encoding="utf-8", errors="ignore")
            modified = False

            # Timezone
            if "persist.sys.timezone=" in content:
                content = re.sub(
                    r"persist\.sys\.timezone=.*",
                    "persist.sys.timezone=Asia/Shanghai",
                    content,
                )
                modified = True

            # Global replacements (port -> base)
            replacements = [
                (self.ctx.port_device_code, self.ctx.base_device_code),
                (self.ctx.port_product_model, self.ctx.base_product_model),
                (self.ctx.port_product_name, self.ctx.base_product_name),
                (self.ctx.port_my_product_type, self.ctx.base_my_product_type),
                (self.ctx.port_product_device, self.ctx.base_product_device),
                # Vendor device and model (reliable identifiers)
                (self.ctx.port_vendor_device, self.ctx.base_vendor_device),
                (self.ctx.port_vendor_model, self.ctx.base_vendor_model),
            ]

            for old_val, new_val in replacements:
                if old_val and new_val and old_val != new_val:
                    if old_val in content:
                        content = content.replace(old_val, new_val)
                        modified = True

            # Display ID
            if self.ctx.target_display_id:
                content = re.sub(
                    r"ro\.build\.display\.id=.*",
                    f"ro.build.display.id={self.ctx.target_display_id}",
                    content,
                )
                modified = True

            # Region lock
            content = re.sub(
                r"ro\.oplus\.radio\.global_regionlock\.enabled=.*",
                "ro.oplus.radio.global_regionlock.enabled=false",
                content,
            )
            content = re.sub(
                r"persist\.sys\.radio\.global_regionlock\.allcheck=.*",
                "persist.sys.radio.global_regionlock.allcheck=false",
                content,
            )
            content = re.sub(
                r"ro\.oplus\.radio\.checkservice=.*",
                "ro.oplus.radio.checkservice=false",
                content,
            )
            modified = True

            if modified:
                build_prop.write_text(content, encoding="utf-8")

    def _modify_my_product_props(self):
        """Modify my_product build.prop patches - port.sh lines 1378-1522"""
        target_my_product = self.target_dir / "my_product"
        if not target_my_product.exists():
            return

        bruce_prop = target_my_product / "etc" / "bruce" / "build.prop"
        my_product_prop = target_my_product / "build.prop"

        # Load my_manifest props to avoid duplication
        manifest_prop_file = (
            self.ctx.baserom.extracted_dir / "my_manifest" / "build.prop"
        )
        manifest_props = self._read_prop_to_dict(manifest_prop_file)

        # Market name/enname (Only if NOT in my_manifest)
        if self.ctx.base_market_name:
            if (
                "ro.vendor.oplus.market.name" not in manifest_props
                and "ro.oplus.market.name" not in manifest_props
            ):
                self._add_or_replace_prop(
                    bruce_prop, "ro.vendor.oplus.market.name", self.ctx.base_market_name
                )
        if self.ctx.base_market_enname:
            if (
                "ro.vendor.oplus.market.enname" not in manifest_props
                and "ro.oplus.market.enname" not in manifest_props
            ):
                self._add_or_replace_prop(
                    bruce_prop,
                    "ro.vendor.oplus.market.enname",
                    self.ctx.base_market_enname,
                )

        # Ported by watermark (Modify the effective file)
        target_v_file = my_product_prop if my_product_prop.exists() else bruce_prop
        old_v = self._read_prop_value(
            target_v_file, "ro.build.version.oplusrom.display"
        )
        if old_v and "Ported By" not in old_v:
            self._add_or_replace_prop(
                target_v_file,
                "ro.build.version.oplusrom.display",
                f"{old_v} | Ported By BT",
            )

        # Magic model props
        self._add_or_replace_prop(
            bruce_prop,
            "persist.oplus.prophook.com.oplus.ai.magicstudio",
            f"MODEL:{self.ctx.base_device_code},BRAND:{self.ctx.base_product_model}",
        )
        self._add_or_replace_prop(
            bruce_prop,
            "persist.oplus.prophook.com.oplus.aiunit",
            f"MODEL:{self.ctx.base_device_code},BRAND:{self.ctx.base_product_model}",
        )

        # LCD Density from base (Should stay in main my_product prop)
        if self.ctx.base_rom_density:
            self._add_or_replace_prop(
                my_product_prop, "ro.sf.lcd_density", self.ctx.base_rom_density
            )

    def _modify_system_ext_props(self):
        """Modify system_ext build.prop"""
        target_system_ext = self.target_dir / "system_ext"
        if not target_system_ext.exists():
            return

        system_ext_prop = target_system_ext / "etc" / "build.prop"
        if not system_ext_prop.exists():
            return

        # Brand replacement
        if (
            self.ctx.port_is_coloros_global == False
            and self.ctx.port_android_version
            and int(self.ctx.port_android_version) < 16
        ):
            if self.ctx.base_vendor_brand and self.ctx.port_vendor_brand:
                base_brand_lower = self.ctx.base_vendor_brand.lower()
                port_brand_lower = self.ctx.port_vendor_brand.lower()
                if base_brand_lower != port_brand_lower:
                    content = system_ext_prop.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    content = re.sub(
                        r"ro\.oplus\.image\.system_ext\.brand=.*",
                        f"ro.oplus.image.system_ext.brand={base_brand_lower}",
                        content,
                    )
                    system_ext_prop.write_text(content, encoding="utf-8")

    def _add_or_replace_prop(self, prop_file: Path, key: str, value: str):
        """Add or replace a property in build.prop"""
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding="utf-8")

        content = prop_file.read_text(encoding="utf-8", errors="ignore")

        # Check if exists
        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            content = re.sub(
                rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE
            )
        else:
            content += f"\n{key}={value}\n"

        prop_file.write_text(content, encoding="utf-8")

    def _add_prop(self, prop_file: Path, prop_line: str):
        """Add a property line to build.prop"""
        if not prop_file.exists():
            prop_file.parent.mkdir(parents=True, exist_ok=True)
            prop_file.write_text("", encoding="utf-8")

        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        content += f"\n{prop_line}\n"
        prop_file.write_text(content, encoding="utf-8")

    def _read_prop_value(self, file_path, key):
        if not file_path.exists():
            return None
        with open(file_path, "r", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
        return None
