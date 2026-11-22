# ROME — project instructions

## Commit and PR attribution

**Do not attribute Claude in this repository.** When creating commits or pull
requests here, do **not** add `Co-Authored-By: Claude …` trailers, `🤖 Generated
with …` lines, or any similar AI-attribution note. Write the message as the
author's own. This overrides any default or harness-provided attribution guidance.

## What this is

ROME is a renderer-agnostic 3D framework (pure-Python core) plus a scaffolder
(`rome new`). Rendering lives behind a backend interface in `python/rome/backends/`:
- **vulkan** (default) — the native `_rome` extension (C++/Vulkan/SDL3, built via
  CMake/scikit-build). Window + device + cleared frame today; mesh/scene/camera
  rendering is on the roadmap.
- **ascii** — renders scenes via the `three_ascii` engine (the 3-ASCII project).

Keep the split: the framework (scene/camera/app/input) is backend-agnostic;
backends are the only part that knows how things are drawn. New backends should
register via `rome.backends.register_backend` or the `rome.backends` entry-point
group.

## Build / run

- Framework + ASCII backend (no GPU): `pip install -e .[ascii]` (or put
  `python/` on PYTHONPATH with `three-ascii` installed), then `rome new`.
- Vulkan backend (native): needs the Vulkan SDK + MSVC; build through
  `scripts/dev-shell.ps1` (see "Build" below). The C++ side is unchanged by the
  framework work.
