"""Cross-version checks for linked Windows state paths."""

from __future__ import annotations

from pathlib import Path
import stat


def is_link_or_junction(path: Path) -> bool:
    """Reject symlinks and Windows junction/reparse points on Python 3.11+."""

    if path.is_symlink():
        return True
    native_check = getattr(path, "is_junction", None)
    if native_check is not None:
        return bool(native_check())
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
