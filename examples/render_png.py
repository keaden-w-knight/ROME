"""Render a scene off-screen to a PNG (no interactive window needed).

    python examples/render_png.py out.png

Uses the default (vulkan) backend's off-screen path, so it's a handy way to see
what the GPU renderer produces — for screenshots, docs, or tests.
"""

import sys

import rome


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "rome_scene.png"
    width, height = 960, 600

    scene = rome.Scene()
    scene.add(rome.Mesh.sphere(), position=(-2.6, 0.0, 0.0), scale=0.9)
    scene.add(rome.Mesh.sphere(), position=(0.0, 0.0, 0.0), scale=1.3)
    scene.add(rome.Mesh.cube(), position=(2.6, 0.3, 0.0), rotation=(0.4, 0.7, 0.0), scale=0.9)
    scene.add(rome.Mesh.sphere(16, 10), position=(0.0, -1.7, 2.0), scale=0.6)

    camera = rome.Camera(position=(2.5, 2.0, -7.0), target=(0.0, 0.0, 0.0), fov=55.0)

    app = rome.App(scene=scene, camera=camera, backend="vulkan", width=width, height=height)
    print("rendering with:", app.info())
    rgba = app.render_image(width, height)
    app.close()

    rome.save_png(out, width, height, rgba)
    print(f"wrote {out} ({width}x{height})")


if __name__ == "__main__":
    main()
