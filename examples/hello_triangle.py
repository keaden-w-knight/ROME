"""The Python-side equivalent of examples/hello_triangle.cpp.

Run it from the build tree with:

    python examples/hello_triangle.py
"""

import math
import sys
from pathlib import Path

# Make the freshly built package importable without installing it.
_build_bin = Path(__file__).resolve().parent.parent / "build" / "msvc-debug" / "bin"
if _build_bin.is_dir():
    sys.path.insert(0, str(_build_bin))

import rome  # noqa: E402


def main() -> int:
    app = rome.App(
        width=1280,
        height=720,
        title="ROME - hello triangle (Python)",
        clear_color=(0.05, 0.05, 0.08),
    )
    print(f"rome {rome.__version__} on {app.gpu_name}")
    print("Press Escape or close the window to exit.")

    while app.tick():
        # Drive the clear colour from Python every frame, so the window is
        # visibly being controlled from this side of the boundary.
        pulse = 0.5 + 0.5 * math.sin(app.elapsed * 1.5)
        app.clear_color = (0.04 + 0.06 * pulse, 0.04, 0.10 + 0.10 * pulse)

        if app.frame_count % 120 == 0 and app.frame_count:
            print(f"frame {app.frame_count:>6}   {app.fps:6.1f} fps")

    print(f"Rendered {app.frame_count} frames in {app.elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
