# mygame

A game built on [ROME](https://github.com/keaden-w-knight/ROME).

```bash
python main.py
```

Controls (ascii backend): **W/A/S/D** orbit · **Q/E** zoom · **R** auto-spin · **Esc** quit

## Layout

- `main.py` — entry point: loads config, builds the scene, runs the loop.
- `game/world.py` — builds the scene; also loads any `.obj` in `assets/`.
- `game/player.py` — player/camera control from input.
- `assets/` — drop models and other assets here.
- `config/game.toml` — title, backend, window size, camera.

Switch renderer in `config/game.toml` (`backend = "vulkan"` or `"ascii"`).
