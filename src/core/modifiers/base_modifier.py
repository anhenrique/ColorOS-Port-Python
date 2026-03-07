"""Base modifier class with common utilities."""

import logging
from pathlib import Path


class PathCache:
    """Cache for file and directory path lookups to avoid repeated scans."""

    def __init__(self):
        self._file_cache = {}
        self._dir_cache = {}

    def find_file(self, root_dir: Path, filename: str) -> Path | None:
        """Find a file recursively with caching."""
        cache_key = (str(root_dir), filename)
        if cache_key in self._file_cache:
            cached_path = self._file_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._file_cache[cache_key]

        if not root_dir.exists():
            self._file_cache[cache_key] = None
            return None

        try:
            result = next(root_dir.rglob(filename))
            self._file_cache[cache_key] = result
            return result
        except StopIteration:
            self._file_cache[cache_key] = None
            return None

    def find_dir(self, root_dir: Path, dirname: str) -> Path | None:
        """Find a directory recursively with caching."""
        cache_key = (str(root_dir), dirname)
        if cache_key in self._dir_cache:
            cached_path = self._dir_cache[cache_key]
            if cached_path and cached_path.exists():
                return cached_path
            del self._dir_cache[cache_key]

        if not root_dir.exists():
            self._dir_cache[cache_key] = None
            return None

        for p in root_dir.rglob(dirname):
            if p.is_dir() and p.name == dirname:
                self._dir_cache[cache_key] = p
                return p

        self._dir_cache[cache_key] = None
        return None

    def clear(self):
        """Clear all caches."""
        self._file_cache.clear()
        self._dir_cache.clear()


class BaseModifier:
    """Base class for all modifiers with common utilities."""

    def __init__(self, context, name: str):
        self.ctx = context
        self.name = name
        self.logger = logging.getLogger(name)
        self.path_cache = PathCache()

    def _find_file_recursive(self, root_dir: Path, filename: str) -> Path | None:
        """Find a file recursively in a directory (uses cache)."""
        return self.path_cache.find_file(root_dir, filename)

    def _find_dir_recursive(self, root_dir: Path, dirname: str) -> Path | None:
        """Find a directory recursively in a directory (uses cache)."""
        return self.path_cache.find_dir(root_dir, dirname)

    def _is_eu_rom(self) -> bool:
        """Check if port ROM is EU/Global version."""
        return getattr(self.ctx, "is_port_eu_rom", False)

    def _get_prop(self, key: str, default: str = "") -> str:
        """Get property from context's port ROM."""
        return self.ctx.port.get_prop(key, default)

    def run(self) -> bool:
        """Execute the modification. Subclasses must implement this."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement run()")
