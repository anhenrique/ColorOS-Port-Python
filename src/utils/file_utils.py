import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def clean_work_dir(work_dir: Path) -> None:
    """Clean and recreate working directory.

    Args:
        work_dir: Path to the working directory to clean
    """
    if work_dir.exists():
        logger.warning(f"Cleaning working directory: {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
