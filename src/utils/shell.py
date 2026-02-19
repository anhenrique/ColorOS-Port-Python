import subprocess
import logging
import shlex
import os
import platform
from typing import Optional, List, Union
from pathlib import Path

logger = logging.getLogger(__name__)

class Shell:
    @staticmethod
    def run(command: str, cwd: Optional[str] = None, check: bool = True, capture_output: bool = True) -> str:
        logger.debug(f"Running command: {command}")
        if not command:
            return ""
        
        # Prepare environment with LD_LIBRARY_PATH
        env = os.environ.copy()
        
        # Determine project root (assuming this file is in src/utils/)
        project_root = Path(__file__).resolve().parent.parent.parent
        lib_path = project_root / "bin" / "linux" / "x86_64" / "lib64"
        
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib_path}:{current_ld}"

        try:
            if capture_output:
                result = subprocess.run(
                    shlex.split(command),
                    cwd=cwd,
                    check=check,
                    capture_output=True,
                    text=True,
                    env=env
                )
                return result.stdout.strip()
            else:
                # Stream output directly to console
                result = subprocess.run(
                    shlex.split(command),
                    cwd=cwd,
                    check=check,
                    capture_output=False, # This pipes directly to stdout/stderr
                    text=True,
                    env=env
                )
                return "" # No output captured
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {command}")
            if capture_output:
                logger.error(f"Error output: {e.stderr}")
            if check:
                raise e
            return ""


class ShellRunner:
    def __init__(self):
        self.logger = logging.getLogger("Shell")
        
        system = platform.system().lower()
        if system == "darwin":
            self.os_name = "darwin"
        elif system == "linux":
            self.os_name = "linux"
        else:
            self.os_name = "windows"

        machine = platform.machine().lower()
        if machine in ["x86_64", "amd64"]:
            self.arch = "x86_64"
        elif machine in ["aarch64", "arm64"]:
            self.arch = "aarch64"
        else:
            self.arch = "x86_64"

        project_root = Path(__file__).resolve().parent.parent.parent
        self.bin_dir = project_root / "bin" / self.os_name / self.arch

        if not self.bin_dir.exists():
            self.logger.warning(f"Binary directory not found: {self.bin_dir}")
            
        self.otatools_bin = project_root / "otatools" / "bin"

    def get_binary_path(self, tool_name: str) -> Path:
        bin_path = self.bin_dir / tool_name
        if bin_path.exists():
            return bin_path

        ota_path = self.otatools_bin / tool_name
        if ota_path.exists():
            return ota_path

        common_bin = self.bin_dir.parent.parent / tool_name
        if common_bin.exists():
            return common_bin

        return Path(tool_name)

    def run(self, cmd: Union[str, List[str]], cwd: Optional[Path] = None, 
            check: bool = True, capture_output: bool = False, 
            env: Optional[dict] = None, silent: bool = False) -> subprocess.CompletedProcess:
        if isinstance(cmd, list):
            tool = cmd[0]
            tool_path = self.get_binary_path(tool)
            if tool_path.is_absolute() and tool_path.exists():
                cmd[0] = str(tool_path)
                if not os.access(tool_path, os.X_OK):
                    os.chmod(tool_path, 0o755)
        
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
            
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
        if not silent:
            self.logger.debug(f"Running: {cmd_str}")

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=check,
                shell=(isinstance(cmd, str)),
                text=True,
                capture_output=capture_output,
                env=run_env
            )
            return result
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed with return code {e.returncode}")
            self.logger.error(f"Command: {cmd_str}")
            if e.stderr:
                self.logger.error(f"Stderr: {e.stderr.strip()}")
            raise e

    def run_java_jar(self, jar_path: Union[str, Path], args: List[str], **kwargs):
        full_jar_path = self.get_binary_path(str(jar_path))
        cmd = ["java", "-jar", str(full_jar_path)] + args
        return self.run(cmd, **kwargs)
