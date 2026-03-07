import logging
import sys
from pathlib import Path


def setup_logging(work_dir: Path, debug: bool = False) -> Path:
    """Setup logging with console and file handlers.

    Args:
        work_dir: Working directory for log file
        debug: Enable debug level logging if True

    Returns:
        Path to the log file
    """
    level = logging.DEBUG if debug else logging.INFO

    work_dir.mkdir(parents=True, exist_ok=True)
    log_file = work_dir / "port.log"

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    root_logger.handlers = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")

    return log_file
