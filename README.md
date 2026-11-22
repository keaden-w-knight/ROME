# ROME

A Vulkan-backed 3D viewport with Python bindings — aiming at the overlap
between pygame (own your loop, handle your own events, stay out of the way)
and Babylon.js (scenes, meshes, cameras, materials).

```python
import rome

app = rome.App(title="Viewport", clear_color=(0.05, 0.05, 0.08))
print(app.gpu_name)          # NVIDIA T1200 Laptop GPU

while app.tick():            # your loop, your frame
    ...
```

Current status: **the vertical slice is working end to end.** A window, a
Vulkan 1.3 device, a swapchain and a rendered triangle, reachable from both
C++ and Python. The scene graph is not built yet — see [Roadmap](#roadmap).

## Layout

```
include/rome/     Public headers (App, Window, types) — the C++ interface
  gfx/            Vulkan internals: context, swapchain, renderer
src/rome/         Implementations
shaders/          GLSL, compiled to SPIR-V and embedded into the binary
python/           nanobind module (_rome) + the `rome` Python package
examples/         hello_triangle in both C++ and Python
tests/            CTest suite (no GPU or window required)
cmake/            Dependency fetching and the shader build rule
scripts/          dev-shell.ps1 — the MSVC build environment
```

`rome_core` holds all the logic; the C++ example and the Python extension are
both thin shells over the same library, so nothing is reachable from one and
not the other.

## Toolchain

| Component  | Version     | Notes                                     |
|------------|-------------|-------------------------------------------|
| MSVC       | 19.44.35228 | VS 2022 Build Tools, x64                  |
| Vulkan SDK | 1.4.341.1   | `glslc`, validation layers                |
| CMake      | 4.3.2       | Ninja generator                           |
| Python     | 3.13.14     | python.org, MSVC/UCRT-built               |

Fetched at configure time, no package manager needed:

| Library  | Version        | Role                                |
|----------|----------------|-------------------------------------|
| SDL3     | 3.4.14         | Window, events, input               |
| nanobind | 2.15.0         | C++ ↔ Python bindings               |
| vk-bootstrap | 1.4.341    | Instance/device/swapchain selection |
| VMA      | 3.4.0          | GPU memory allocation               |
| GLM      | 1.0.3          | Vector and matrix maths             |

vk-bootstrap is pinned to the same version as the installed Vulkan SDK; a
newer one can reference structs the SDK headers do not have yet.

## Build

Everything runs through `scripts/dev-shell.ps1`, which imports the MSVC
environment. It is needed because the Ninja generator expects `cl.exe` and the
Windows SDK to already be on `PATH`.

```powershell
# Configure the current shell, then work normally
. .\scripts\dev-shell.ps1
cmake --preset msvc-debug
cmake --build --preset msvc-debug
ctest --preset msvc-debug

# Or run a single command in a configured sub-shell
.\scripts\dev-shell.ps1 -Run "cmake --build --preset msvc-debug"
```

Presets: `msvc-debug`, `msvc-release` (warnings are errors),
`msvc-relwithdebinfo`. Each configures into `build/<preset>/`, with binaries
in `build/<preset>/bin/`.

Run the demos:

```powershell
.\build\msvc-debug\bin\hello_triangle.exe

$env:PYTHONPATH = "$PWD\build\msvc-debug\bin"
python examples\hello_triangle.py
```

Build an installable wheel:

```powershell
.\scripts\dev-shell.ps1 -Run "python -m pip wheel . -w dist --no-deps"
```

## In VS Code

- **Ctrl+Shift+B** — build the debug preset
- **F5** — debug the C++ demo, the tests, or the Python demo (pick from the
  dropdown). `C++: attach to python.exe` puts native breakpoints under a
  running Python script.
- **Test Explorer** — runs both CTest tests
- New terminals open in the `ROME dev (MSVC)` profile, already in the build
  environment
- IntelliSense flags come from CMake Tools, so they track `CMakeLists.txt`;
  `clang-format` runs on save

## Design notes

**Vulkan 1.3 core, no legacy scaffolding.** Dynamic rendering means there is
no `VkRenderPass` and no `VkFramebuffer` to keep in step with the swapchain;
synchronization2 supplies the barrier and submit forms. Both are required
device features, so the GPU selection rejects anything older.

**Shaders are embedded, not loaded.** `glslc -mfmt=c` emits SPIR-V as a C
initialiser list at build time, which gets compiled into the binary. A Python
extension is imported from wherever site-packages happens to be, and hunting
for loose `.spv` files at runtime is a reliable source of bugs.

**Presentation semaphores are per swapchain image**, not per frame-in-flight.
A semaphore signalled for presentation stays in use until that specific image
is reacquired, which does not follow the frame-in-flight cycle — sharing them
is a subtle and intermittent source of validation errors.

**MSVC, not MinGW.** The python.org interpreters are MSVC/UCRT-built. MSYS2's
GCC links `msvcrt.dll` instead, and building a CPython extension across that
mismatch is unsupported — no Windows wheel on PyPI is made that way.

## Gotchas on this machine

**`python` on `PATH` is the wrong one.** MSYS2 ships a Python 3.14 that
arrived as a `gdb` dependency, and `C:\msys64\mingw64\bin` sits first on
`PATH`, so a bare `python` resolves to it rather than your python.org 3.13.
It cannot simply be removed — gdb's STL pretty-printers depend on it.
`scripts/dev-shell.ps1` drops MSYS2 from `PATH` and pins the interpreter, so
anything run through it is unaffected. Outside it, prefer `py -3.13`.

**`import rome` needs the DLL directory.** Since Python 3.8, Windows no
longer searches `PATH` for a module's dependencies. `rome/__init__.py` calls
`os.add_dll_directory` on the package directory so the co-located `SDL3.dll`
resolves.

## Roadmap

The current API is deliberately small; the pieces below are what turn it into
the library described at the top.

- [ ] Vertex and index buffers via VMA, with zero-copy numpy interop
- [ ] Camera: perspective/orthographic, orbit and fly controls
- [ ] Transforms and a scene graph
- [ ] Depth buffer and depth testing
- [ ] Mesh primitives (cube, sphere, plane, grid) and glTF loading
- [ ] Materials and basic PBR lighting
- [ ] Input events surfaced to Python (keyboard, mouse, gamepad)
- [ ] Offscreen rendering to a numpy array, for notebooks and tests
