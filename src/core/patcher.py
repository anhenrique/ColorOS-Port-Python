import shutil
import logging
import re
import os
from pathlib import Path
from src.core.context import Context
from src.utils.shell import Shell

logger = logging.getLogger(__name__)

class SmaliPatcher:
    def __init__(self, context: Context):
        self.ctx = context
        self.target_dir = self.ctx.target_dir
        self.tools = self.ctx.tools

    def run(self):
        logger.info("Starting Smali Patching...")
        self._patch_services_jar()
        self._patch_framework_jar()
        self._patch_oplus_services_jar()
        logger.info("Smali Patching Complete.")

    def _patch_services_jar(self):
        jar_path = self.target_dir / "system/framework/services.jar"
        if not jar_path.exists():
            jar_path = self.target_dir / "system/system/framework/services.jar"
            
        if not jar_path.exists():
            logger.warning("services.jar not found, skipping.")
            return

        logger.info(f"Patching {jar_path.name}...")
        temp_dir = self.ctx.work_dir / "temp_services"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        self._decompile_jar(jar_path, temp_dir)

        # 1. Patch PackageManagerServiceUtils.smali (checkDowngrade)
        # Find all smali files recursively
        for smali_file in temp_dir.rglob("PackageManagerServiceUtils.smali"):
            self._patch_method_return(smali_file, "checkDowngrade", "return-void")
            # Also patch matchSignaturesCompat, verifySignatures etc to return false
            self._patch_method_return(smali_file, "matchSignaturesCompat", "return-false")
            self._patch_method_return(smali_file, "matchSignaturesRecover", "return-false")
            self._patch_method_return(smali_file, "verifySignatures", "return-false")

        # 2. Patch ReconcilePackageUtils.smali (ALLOW_NON_PRELOADS_SYSTEM_SHAREDUIDS)
        for smali_file in temp_dir.rglob("ReconcilePackageUtils.smali"):
            self._patch_boolean_field(smali_file, "ALLOW_NON_PRELOADS_SYSTEM_SHAREDUIDS", True)

        self._compile_jar(temp_dir, jar_path)
        shutil.rmtree(temp_dir)

    def _patch_framework_jar(self):
        jar_path = self.target_dir / "system/framework/framework.jar"
        if not jar_path.exists():
             jar_path = self.target_dir / "system/system/framework/framework.jar"

        if not jar_path.exists():
            logger.warning("framework.jar not found, skipping.")
            return

        logger.info(f"Patching {jar_path.name}...")
        temp_dir = self.ctx.work_dir / "temp_framework"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        self._decompile_jar(jar_path, temp_dir)

        # 1. Patch StrictJarVerifier.smali
        for smali_file in temp_dir.rglob("StrictJarVerifier.smali"):
             # verifyMessageDigest -> return true
             self._patch_method_return(smali_file, "verifyMessageDigest", "return-true")
        
        self._compile_jar(temp_dir, jar_path)
        shutil.rmtree(temp_dir)

    def _patch_oplus_services_jar(self):
        jar_path = None
        candidates = [
            self.target_dir / "system/framework/oplus-services.jar",
            self.target_dir / "system/system/framework/oplus-services.jar",
            self.target_dir / "system_ext/framework/oplus-services.jar"
        ]
        
        for p in candidates:
            if p.exists():
                jar_path = p
                break
        
        if not jar_path:
            return

        logger.info(f"Patching {jar_path.name}...")
        temp_dir = self.ctx.work_dir / "temp_oplus_services"
        if temp_dir.exists():
             shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        self._decompile_jar(jar_path, temp_dir)
        
        # Patch OplusBgSceneManager.smali (isGmsRestricted -> false)
        for smali_file in temp_dir.rglob("OplusBgSceneManager.smali"):
             self._patch_method_return(smali_file, "isGmsRestricted", "return-false")

        self._compile_jar(temp_dir, jar_path)
        shutil.rmtree(temp_dir)


    def _decompile_jar(self, jar_path, out_dir):
        apk_editor = self.tools.get_tool("APKEditor.jar")
        # Ensure we use java from path or context
        cmd = f"java -jar {apk_editor} d -f -i {jar_path} -o {out_dir}"
        logger.info(f"Decompiling: {cmd}")
        Shell.run(cmd)

    def _compile_jar(self, src_dir, out_jar):
        apk_editor = self.tools.get_tool("APKEditor.jar")
        cmd = f"java -jar {apk_editor} b -f -i {src_dir} -o {out_jar}"
        logger.info(f"Compiling: {cmd}")
        Shell.run(cmd)

    # --- Smali Logic ---

    def _patch_method_return(self, file_path: Path, method_name: str, return_type: str):
        """
        Simplistic method patching:
        Finds .method ... method_name(...)
        Replaces the body with just the return statement.
        """
        content = file_path.read_text()
        
        # Regex to match method start and end
        # .method [modifiers] methodName(args)ReturnType
        # ... body ...
        # .end method
        
        # We need to be careful not to match too greedily.
        # This regex looks for the method declaration, captures everything until .end method
        pattern = re.compile(
            r"(\.method.*? " + re.escape(method_name) + r"\(.*?\).*?)([\s\S]*?)(\.end method)",
            re.MULTILINE
        )
        
        def replacement(match):
            header = match.group(1)
            # body = match.group(2)
            footer = match.group(3)
            
            new_body = "\n    .locals 1\n"
            
            if return_type == "return-void":
                new_body += "    return-void\n"
            elif return_type == "return-true":
                new_body += "    const/4 v0, 0x1\n    return v0\n"
            elif return_type == "return-false":
                new_body += "    const/4 v0, 0x0\n    return v0\n"
            
            return f"{header}{new_body}{footer}"

        new_content, count = pattern.subn(replacement, content)
        if count > 0:
            logger.info(f"Patched {method_name} in {file_path.name}")
            file_path.write_text(new_content)

    def _patch_boolean_field(self, file_path: Path, field_name: str, value: bool):
        # Look for sput-boolean <reg>, <class>->FIELD_NAME
        # And ensure the register is set to value before.
        # This is harder to do safely with regex only because we need to find where it's initialized (usually <clinit>)
        # Alternative: Find the field definition and ensure it's initialized to true? 
        # Static fields are initialized in <clinit>.
        
        # Original script logic:
        # grep -n "sput-boolean .*${ALLOW_NON_PRELOADS_SYSTEM_SHAREDUIDS}"
        # insert "const/4 reg, 0x1" before it.
        
        lines = file_path.read_text().splitlines()
        new_lines = []
        patched = False
        
        for line in lines:
            if f"->{field_name}:Z" in line and "sput-boolean" in line:
                # Found the initialization
                # Example: sput-boolean v0, L...;->ALLOW...:Z
                # Extract register
                match = re.search(r"sput-boolean (v\d+),", line)
                if match:
                    reg = match.group(1)
                    val_hex = "0x1" if value else "0x0"
                    # Insert override
                    new_lines.append(f"    const/4 {reg}, {val_hex}")
                    logger.info(f"Patched field {field_name} initialization in {file_path.name}")
                    patched = True
            
            new_lines.append(line)
            
        if patched:
            file_path.write_text("\n".join(new_lines))
