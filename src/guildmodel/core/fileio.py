"""Writing a file so that an interruption leaves the old one, never a stub."""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["write_text_atomic"]


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """`Path.write_text` through a sibling renamed over the file.

    `write_text` truncates first, so a crash or a full disk mid-write left an
    empty file: a user's tool, material or style library, or the default bed,
    read back as nothing and replaced by the shipped one on the next save
    (the 2.0 bug hunt). The project file and the preferences were already
    written this way.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding=encoding) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
