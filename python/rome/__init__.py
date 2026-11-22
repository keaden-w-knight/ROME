"""ROME - a Vulkan-backed 3D viewport you can drive from Python.

The native extension does the rendering; this module is the friendly surface
over it. Two loop styles are supported, mirroring how pygame and a scene
library each expect to be used:

    # You own the loop (pygame style)
    import rome

    app = rome.App(title="Viewport")
    while app.tick():
        ...                     # your per-frame work

    # ROME owns the loop
    with rome.App() as app:
        app.run()
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The extension links SDL3 as a DLL that sits beside it in the package. Since
# Python 3.8 Windows no longer searches PATH for a module's dependencies, so
# the directory has to be registered explicitly before the import.
if sys.platform == "win32":  # pragma: no cover - platform specific
    _package_dir = Path(__file__).parent
    if hasattr(os, "add_dll_directory") and _package_dir.is_dir():
        os.add_dll_directory(str(_package_dir))

from ._rome import App, RomeError, __version__  # noqa: E402

__all__ = ["App", "RomeError", "__version__"]
