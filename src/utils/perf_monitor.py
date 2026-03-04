"""
Performance monitoring utilities for ColorOS Porting Tool.
Provides memory tracking, CPU usage monitoring, and dynamic worker adjustment.
"""

import os
import logging
import psutil
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import timedelta

logger = logging.getLogger(__name__)


@dataclass
class ResourceSnapshot:
    """Snapshot of system resource usage"""

    memory_used_mb: float = 0.0
    memory_available_mb: float = 0.0
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    timestamp: float = 0.0


class PerformanceMonitor:
    """
    Monitor system resources and provide recommendations for optimal performance.
    """

    # Memory thresholds (in MB)
    MEMORY_LOW_THRESHOLD = 500
    MEMORY_CRITICAL_THRESHOLD = 200

    # Worker adjustment thresholds
    MEMORY_HIGH_PERCENT = 80.0
    MEMORY_CRITICAL_PERCENT = 90.0

    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.snapshots: List[ResourceSnapshot] = []
        self._last_adjustment_time = 0.0
        self._current_workers = self._get_optimal_workers()

    def _get_optimal_workers(self) -> int:
        """Calculate optimal worker count based on CPU cores"""
        cpu_count = os.cpu_count() or 4
        # For I/O bound tasks, use more workers
        # For CPU bound tasks, use fewer workers
        return max(cpu_count // 2 + 1, 2)

    def get_snapshot(self) -> ResourceSnapshot:
        """Get current resource usage snapshot"""
        import time

        snapshot = ResourceSnapshot(
            memory_used_mb=self.process.memory_info().rss / 1024 / 1024,
            memory_available_mb=psutil.virtual_memory().available / 1024 / 1024,
            memory_percent=psutil.virtual_memory().percent,
            cpu_percent=self.process.cpu_percent(),
            timestamp=time.time(),
        )

        self.snapshots.append(snapshot)
        return snapshot

    def get_memory_usage(self) -> Dict[str, float]:
        """Get detailed memory usage information"""
        mem_info = self.process.memory_info()
        virtual_mem = psutil.virtual_memory()

        return {
            "rss_mb": mem_info.rss / 1024 / 1024,
            "vms_mb": mem_info.vms / 1024 / 1024,
            "percent": virtual_mem.percent,
            "available_mb": virtual_mem.available / 1024 / 1024,
            "total_mb": virtual_mem.total / 1024 / 1024,
        }

    def should_reduce_workers(self, current_workers: int) -> tuple[bool, int]:
        """
        Determine if worker count should be reduced based on resource usage.

        Returns:
            Tuple of (should_reduce, recommended_workers)
        """
        import time

        snapshot = self.get_snapshot()

        # Check if enough time has passed since last adjustment
        time_since_adjustment = snapshot.timestamp - self._last_adjustment_time
        if time_since_adjustment < 5.0:  # Minimum 5 seconds between adjustments
            return False, current_workers

        self._last_adjustment_time = snapshot.timestamp

        # Critical: reduce to minimum
        if snapshot.memory_percent >= self.MEMORY_CRITICAL_PERCENT:
            recommended = max(1, current_workers // 2)
            logger.warning(
                f"Memory critical ({snapshot.memory_percent:.1f}%), "
                f"reducing workers from {current_workers} to {recommended}"
            )
            return True, recommended

        # High: consider reducing
        if snapshot.memory_percent >= self.MEMORY_HIGH_PERCENT:
            recommended = max(2, current_workers - 1)
            if recommended < current_workers:
                logger.info(
                    f"Memory high ({snapshot.memory_percent:.1f}%), "
                    f"consider reducing workers from {current_workers} to {recommended}"
                )
                return True, recommended

        return False, current_workers

    def get_dynamic_workers(self, base_workers: int, is_io_bound: bool = True) -> int:
        """
        Get dynamically adjusted worker count based on current resource usage.

        Args:
            base_workers: Base worker count to adjust from
            is_io_bound: Whether the task is I/O bound (allows more workers)

        Returns:
            Recommended worker count
        """
        should_reduce, recommended = self.should_reduce_workers(base_workers)

        if should_reduce:
            return recommended

        # If resources are fine, can increase slightly for I/O bound tasks
        snapshot = self.get_snapshot()

        if is_io_bound and snapshot.memory_percent < 50.0:
            cpu_count = os.cpu_count() or 4
            max_workers = min(base_workers + 2, cpu_count, 8)
            return max_workers

        return base_workers

    def log_resource_status(self, stage: str = ""):
        """Log current resource status"""
        snapshot = self.get_snapshot()
        mem_info = self.get_memory_usage()

        status_msg = (
            f"[Resource Status] {stage}\n"
            f"  Memory: {mem_info['rss_mb']:.1f}MB used / "
            f"{mem_info['available_mb']:.1f}MB available "
            f"({mem_info['percent']:.1f}%)\n"
            f"  Virtual Memory: {mem_info['vms_mb']:.1f}MB\n"
            f"  Current Workers: {self._current_workers}"
        )

        logger.info(status_msg)

    def print_summary(self):
        """Print performance summary"""
        if not self.snapshots:
            logger.info("No resource snapshots recorded")
            return

        avg_memory = sum(s.memory_used_mb for s in self.snapshots) / len(self.snapshots)
        max_memory = max(s.memory_used_mb for s in self.snapshots)
        avg_memory_percent = sum(s.memory_percent for s in self.snapshots) / len(
            self.snapshots
        )

        summary = f"""
{"=" * 60}
Performance Monitoring Summary
{"=" * 60}
  Snapshots collected: {len(self.snapshots)}
  Memory Usage:
    - Average: {avg_memory:.1f} MB
    - Peak: {max_memory:.1f} MB
    - Average System Memory: {avg_memory_percent:.1f}%
  Recommended Workers: {self._current_workers}
{"=" * 60}
"""
        logger.info(summary)


def get_optimal_worker_count(task_type: str = "io_bound") -> int:
    """
    Get optimal worker count for different task types.

    Args:
        task_type: Type of task ("io_bound", "cpu_bound", "mixed")

    Returns:
        Recommended worker count
    """
    cpu_count = os.cpu_count() or 4

    if task_type == "cpu_bound":
        # CPU-bound tasks: use fewer workers
        return max(cpu_count // 4 + 1, 2)
    elif task_type == "mixed":
        # Mixed tasks: balanced approach
        return max(cpu_count // 3 + 1, 3)
    else:  # io_bound
        # I/O-bound tasks: can use more workers
        return max(cpu_count // 2 + 1, 4)


# Global performance monitor instance
_global_monitor: Optional[PerformanceMonitor] = None


def get_monitor() -> PerformanceMonitor:
    """Get or create global performance monitor"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def reset_monitor():
    """Reset global monitor"""
    global _global_monitor
    _global_monitor = PerformanceMonitor()
