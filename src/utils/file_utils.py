import logging
import shutil
import subprocess
import os
from pathlib import Path
from typing import Union, Optional

logger = logging.getLogger(__name__)

def clean_work_dir(work_dir: Path) -> None:
    """Clean and recreate working directory."""
    if work_dir.exists():
        logger.warning(f"Cleaning working directory: {work_dir}")
        remove_path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

def copy_dir(src: Union[str, Path], dst: Union[str, Path], symlinks: bool = True) -> bool:
    """
    High-performance directory copy using native 'cp' command.
    Falls back to shutil.copytree if native command fails.
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()

    if not src_path.exists():
        logger.error(f"Source directory does not exist: {src_path}")
        return False

    # Try native cp -af for performance and attribute preservation
    try:
        # -a: archive (preserve attributes, recursion, symlinks)
        # -f: force
        cmd = ["cp", "-af", f"{src_path}/.", str(dst_path)]
        dst_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.debug(f"Native cp failed, falling back to shutil: {e}")
        try:
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path, symlinks=symlinks, dirs_exist_ok=True)
            return True
        except Exception as e2:
            logger.error(f"Failed to copy directory {src} to {dst}: {e2}")
            return False

def copy_file(src: Union[str, Path], dst: Union[str, Path]) -> bool:
    """
    Copy a single file using native 'cp' or shutil.copy2.
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()

    try:
        if dst_path.is_dir():
            dst_path = dst_path / src_path.name
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Using cp -f for simple file copy
        subprocess.run(["cp", "-f", str(src_path), str(dst_path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            shutil.copy2(src_path, dst_path)
            return True
        except Exception as e:
            logger.error(f"Failed to copy file {src} to {dst}: {e}")
            return False

def move_path(src: Union[str, Path], dst: Union[str, Path]) -> bool:
    """
    Move a file or directory using native 'mv' or shutil.move.
    """
    src_path = Path(src).resolve()
    dst_path = Path(dst).resolve()

    try:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mv", "-f", str(src_path), str(dst_path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            shutil.move(str(src_path), str(dst_path))
            return True
        except Exception as e:
            logger.error(f"Failed to move {src} to {dst}: {e}")
            return False

def remove_path(path: Union[str, Path]) -> bool:
    """
    Remove a file or directory using native 'rm -rf' or shutil.
    """
    target_path = Path(path).resolve()
    if not target_path.exists():
        return True

    try:
        subprocess.run(["rm", "-rf", str(target_path)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to remove {path}: {e}")
            return False
