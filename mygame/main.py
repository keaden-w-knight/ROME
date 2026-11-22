"""mygame — a ROME game. You own this file; ROME just renders."""
from __future__ import annotations

import tomllib
from pathlib import Path

import rome

from game.player import Player
from game.world import build_scene

ROOT = Path(__file__).parent


def load_config() -> dict:
    with (ROOT / "config" / "game.toml").open("rb") as f:
        return tomllib.load(f)


def main() -> None:
    cfg = load_config()
    scene = build_scene(ROOT, cfg)
    player = Player(distance=cfg["camera"]["distance"], fov=cfg["camera"]["fov"])

    app = rome.App(
        scene=scene,
        camera=player.camera,
        backend=cfg["render"]["backend"],
        width=cfg["window"]["width"],
        height=cfg["window"]["height"],
        title=cfg["game"]["title"],
    )
    print(f"{cfg['game']['title']} — {app.info()}")

    def update(app: rome.App) -> None:
        if app.input.down("escape"):
            app.close()
            return
        player.update(app.dt, app.input)
        app.camera = player.camera

    app.run(update)


if __name__ == "__main__":
    main()
