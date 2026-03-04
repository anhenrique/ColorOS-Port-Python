"""
Progress indicator and performance timing utilities for ColorOS Porting Tool
"""

import time
import logging
from typing import Optional, Dict, List
from contextlib import contextmanager
from datetime import timedelta

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Tracks progress of long-running operations with optimized logging"""

    def __init__(
        self, total: int, description: str = "Processing", unit: str = "items"
    ):
        self.total = total
        self.current = 0
        self.description = description
        self.unit = unit
        self.start_time = time.time()
        self._last_log_time = 0
        self._last_log_count = 0
        # Dynamic log interval based on total count
        # Log at least 10 times during the operation, but no more than every 2 seconds
        self._log_interval = max(2.0, 60.0 / max(total // 10 + 1, 1))
        self._log_threshold = max(1, total // 20)  # Log every 5% of progress

    def update(self, increment: int = 1, message: Optional[str] = None):
        """Update progress counter with optimized logging"""
        self.current += increment

        # Log based on both time and progress threshold
        current_time = time.time()
        should_log = (
            current_time - self._last_log_time >= self._log_interval
            or self.current - self._last_log_count >= self._log_threshold
        )

        if should_log:
            self._log_progress(message)
            self._last_log_time = current_time
            self._last_log_count = self.current

    def _log_progress(self, message: Optional[str] = None):
        """Log current progress with optimized formatting"""
        if self.total > 0:
            percentage = (self.current / self.total) * 100
            elapsed = time.time() - self.start_time

            if self.current > 0:
                eta_seconds = (elapsed / self.current) * (self.total - self.current)
                eta = timedelta(seconds=int(eta_seconds))
            else:
                eta = "N/A"

            # Use f-string formatting (faster than % formatting)
            progress_msg = (
                f"[{self.description}] {self.current}/{self.total} "
                f"{self.unit} ({percentage:5.1f}%) - ETA: {eta}"
            )
            if message:
                progress_msg += f" - {message}"

            logger.info(progress_msg)
        else:
            logger.info(f"[{self.description}] {self.current} {self.unit} processed")

    def finish(self):
        """Mark progress as complete and log summary"""
        elapsed = time.time() - self.start_time
        elapsed_str = timedelta(seconds=int(elapsed))

        # Calculate throughput
        if elapsed > 0 and self.total > 0:
            rate = self.total / elapsed
            logger.info(
                f"[{self.description}] Completed {self.current}/{self.total} {self.unit} "
                f"in {elapsed_str} ({rate:.2f} {self.unit}/sec)"
            )
        else:
            logger.info(
                f"[{self.description}] Completed {self.current}/{self.total} {self.unit} in {elapsed_str}"
            )


class StageTimer:
    """Timer for tracking stage execution time"""

    def __init__(self):
        self.stages: Dict[str, Dict] = {}
        self._current_stage: Optional[str] = None
        self._start_time: Optional[float] = None

    def start_stage(self, name: str):
        """Start timing a stage"""
        if self._current_stage:
            self.end_stage()

        self._current_stage = name
        self._start_time = time.time()
        self.stages[name] = {"start": self._start_time, "end": None, "duration": None}
        logger.info(f"[Stage] Starting: {name}")

    def end_stage(self):
        """End timing current stage"""
        if not self._current_stage or not self._start_time:
            return

        end_time = time.time()
        duration = end_time - self._start_time
        self.stages[self._current_stage]["end"] = end_time
        self.stages[self._current_stage]["duration"] = duration

        duration_str = timedelta(seconds=int(duration))
        logger.info(f"[Stage] Completed: {self._current_stage} in {duration_str}")

        self._current_stage = None
        self._start_time = None

    def get_summary(self) -> str:
        """Get formatted timing summary"""
        if not self.stages:
            return "No stages recorded"

        total_time = sum(s.get("duration", 0) for s in self.stages.values())

        lines = ["\n" + "=" * 60, "Performance Summary", "=" * 60]

        for name, data in self.stages.items():
            duration = data.get("duration", 0)
            if duration:
                percentage = (duration / total_time * 100) if total_time > 0 else 0
                duration_str = str(timedelta(seconds=int(duration)))
                lines.append(f"  {name:.<40} {duration_str:>10} ({percentage:>5.1f}%)")

        lines.append("-" * 60)
        total_str = str(timedelta(seconds=int(total_time)))
        lines.append(f"  {'Total':.<40} {total_str:>10} (100.0%)")
        lines.append("=" * 60 + "\n")

        return "\n".join(lines)

    def print_summary(self):
        """Print timing summary to log"""
        logger.info(self.get_summary())


# Global stage timer instance
_global_timer: Optional[StageTimer] = None


def get_timer() -> StageTimer:
    """Get or create global stage timer"""
    global _global_timer
    if _global_timer is None:
        _global_timer = StageTimer()
    return _global_timer


def reset_timer():
    """Reset global timer"""
    global _global_timer
    _global_timer = StageTimer()


@contextmanager
def timed_stage(name: str):
    """Context manager for timing a stage"""
    timer = get_timer()
    timer.start_stage(name)
    try:
        yield timer
    except Exception as e:
        logger.error(f"[Stage] Error in {name}: {e}")
        raise
    finally:
        timer.end_stage()


def create_progress_tracker(
    total: int, description: str = "Processing", unit: str = "items"
) -> ProgressTracker:
    """Factory function to create a progress tracker"""
    return ProgressTracker(total, description, unit)
