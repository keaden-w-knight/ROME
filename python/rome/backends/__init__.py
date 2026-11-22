"""Backend registry.

Backends register themselves by name; the built-in ones (vulkan, ascii) are
imported on first use, and third-party backends are discovered through the
``rome.backends`` entry-point group — so a new backend can ship as its own pip
package and appear here with no change to ROME.
"""

from __future__ import annotations

from typing import Callable

from .base import Backend, BackendConfig

#: the backend used when none is named
DEFAULT_BACKEND = "vulkan"

BackendFactory = Callable[[], Backend]

_FACTORIES: dict[str, BackendFactory] = {}
_discovered = False


def register_backend(name: str, factory: BackendFactory) -> None:
    """Register a backend under `name`. `factory` returns a fresh `Backend`."""
    _FACTORIES[name] = factory


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True

    # Built-ins. Each module calls register_backend on import. Import errors
    # (e.g. the native extension or a dependency missing) are deferred to
    # create_backend, so merely listing backends never explodes.
    for mod in ("vulkan", "ascii"):
        try:
            __import__(f"{__name__}.{mod}")
        except Exception:
            pass

    # Third-party plugins.
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="rome.backends"):
            try:
                register_backend(ep.name, ep.load())
            except Exception:
                pass
    except Exception:
        pass


def available_backends() -> list[str]:
    _discover()
    return sorted(_FACTORIES)


def create_backend(name: str | None, config: BackendConfig) -> Backend:
    _discover()
    name = name or DEFAULT_BACKEND
    try:
        factory = _FACTORIES[name]
    except KeyError:
        raise ValueError(
            f"unknown backend {name!r}; available: {', '.join(available_backends()) or 'none'}"
        ) from None
    backend = factory()
    backend.open(config)
    return backend


__all__ = [
    "Backend",
    "BackendConfig",
    "DEFAULT_BACKEND",
    "register_backend",
    "available_backends",
    "create_backend",
]
