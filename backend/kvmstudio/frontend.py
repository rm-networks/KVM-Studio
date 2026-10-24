"""Where the built frontend lives. Kept free of heavy imports: the window
process uses it without loading libvirt."""

from __future__ import annotations

import os
from pathlib import Path


def find_frontend_dir() -> Path | None:
    """Locate the built frontend: explicit override, packaged copy, then source tree."""
    candidates = []
    if override := os.environ.get("KVMSTUDIO_FRONTEND_DIR"):
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates += [here / "static", here.parents[1] / "frontend" / "dist"]
    return next((c for c in candidates if (c / "index.html").is_file()), None)
