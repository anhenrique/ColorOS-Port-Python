import subprocess
import logging
import shlex
from typing import Optional

logger = logging.getLogger(__name__)

class Shell:
    @staticmethod
    def run(command: str, cwd: Optional[str] = None, check: bool = True) -> str:
        logger.debug(f"Running command: {command}")
        if not command:
            return ""
        try:
            result = subprocess.run(
                shlex.split(command),
                cwd=cwd,
                check=check,
                capture_output=True,
                text=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {command}")
            logger.error(f"Error output: {e.stderr}")
            if check:
                raise e
            return ""
