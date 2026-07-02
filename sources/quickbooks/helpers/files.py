"""File-download helpers for Attachable binaries and entity PDFs.

Binaries are written to any fsspec-compatible URL (a local directory,
``s3://bucket/prefix``, ``gs://…``, …); only file *metadata* lands in the
destination tables, with a ``_qbo_file_path`` column pointing at the stored
binary.
"""

from __future__ import annotations

import posixpath
import re

import fsspec


def sanitize_filename(name: str) -> str:
    """Make a QuickBooks file name safe to use as a path segment."""
    cleaned = re.sub(r"[/\\\x00-\x1f]", "_", name).strip() or "unnamed"
    return cleaned


def write_bytes(base_url: str, relative_path: str, content: bytes) -> str:
    """Write ``content`` under ``base_url`` and return the full destination URL."""
    destination = f"{base_url.rstrip('/')}/{relative_path}"
    fs, path = fsspec.core.url_to_fs(destination)
    parent = posixpath.dirname(path)
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(path, "wb") as handle:
        handle.write(content)
    return destination
