"""
Property Modification Utilities - Performance optimization tools.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


class PropCache:
    """Property file cache for performance optimization."""

    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self._prop_files_cache: Optional[List[Path]] = None
        self._prop_content_cache: Dict[Path, str] = {}
        self._prop_dict_cache: Dict[Path, Dict[str, str]] = {}

    @lru_cache(maxsize=128)
    def get_all_prop_files(self, exclude_patterns: Tuple[str, ...] = ()) -> List[Path]:
        """Get all build.prop files with caching and exclusion patterns."""
        if self._prop_files_cache is None:
            prop_files = []
            for prop_file in self.target_dir.rglob("build.prop"):
                if any(pattern in str(prop_file) for pattern in exclude_patterns):
                    continue
                prop_files.append(prop_file)
            self._prop_files_cache = prop_files
        return self._prop_files_cache

    def read_prop_file(self, prop_file: Path) -> str:
        """Read property file with caching."""
        if prop_file not in self._prop_content_cache:
            try:
                content = prop_file.read_text(encoding="utf-8", errors="ignore")
                self._prop_content_cache[prop_file] = content
            except Exception as e:
                logger.error(f"Failed to read {prop_file}: {e}")
                self._prop_content_cache[prop_file] = ""
        return self._prop_content_cache[prop_file]

    def read_prop_to_dict(self, prop_file: Path) -> Dict[str, str]:
        """Read properties file into dictionary with caching."""
        if prop_file not in self._prop_dict_cache:
            props = {}
            content = self.read_prop_file(prop_file)
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                props[key.strip()] = val.strip()
            self._prop_dict_cache[prop_file] = props
        return self._prop_dict_cache[prop_file]

    def find_build_prop(self, partition_dir: Path) -> Path:
        """Find build.prop in partition directory with caching."""
        direct = partition_dir / "build.prop"
        if direct.exists():
            return direct
        nested = partition_dir / "etc" / "build.prop"
        return nested

    def clear_cache(self):
        """Clear all caches."""
        self._prop_files_cache = None
        self._prop_content_cache.clear()
        self._prop_dict_cache.clear()
        self.get_all_prop_files.cache_clear()


def read_prop_to_dict(file_path: Path) -> Dict[str, str]:
    """Read properties file into dictionary."""
    props = {}
    if not file_path.exists():
        return props

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                props[key.strip()] = val.strip()
    except Exception as e:
        logger.error(f"Failed to read {file_path}: {e}")

    return props


def update_or_append_prop(prop_file: Path, key: str, value: str) -> bool:
    """Update existing property or append new one."""
    try:
        content = prop_file.read_text(encoding="utf-8", errors="ignore")

        if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
            # Update existing property
            new_content = re.sub(
                rf"^{re.escape(key)}=.*", f"{key}={value}", content, flags=re.MULTILINE
            )
        else:
            # Append new property
            if content and not content.endswith("\n"):
                content += "\n"
            new_content = content + f"{key}={value}\n"

        if content != new_content:
            prop_file.write_text(new_content, encoding="utf-8")
            return True
        return False

    except Exception as e:
        logger.error(f"Failed to update {prop_file}: {e}")
        return False


def read_prop_value(file_path: Path, key: str) -> Optional[str]:
    """Read specific property value from file."""
    if not file_path.exists():
        return None

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip()
    except Exception as e:
        logger.error(f"Failed to read property {key} from {file_path}: {e}")

    return None


def batch_update_props(prop_file: Path, updates: Dict[str, str]) -> int:
    """Batch update multiple properties in a file."""
    try:
        content = prop_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        changed_count = 0

        # Update existing properties
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                prop_key = stripped.split("=", 1)[0].strip()
                if prop_key in updates:
                    lines[i] = f"{prop_key}={updates[prop_key]}"
                    changed_count += 1

        # Add new properties
        for key, value in updates.items():
            if not any(
                line.strip().startswith(f"{key}=")
                for line in lines
                if line.strip() and not line.strip().startswith("#")
            ):
                lines.append(f"{key}={value}")
                changed_count += 1

        if changed_count > 0:
            prop_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return changed_count

    except Exception as e:
        logger.error(f"Failed to batch update {prop_file}: {e}")
        return 0
