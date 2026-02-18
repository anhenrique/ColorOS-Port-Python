import subprocess
import logging
import shlex
import os
from typing import Optional
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
