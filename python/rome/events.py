"""Events and listeners.

The App fires events every frame; you register listeners to react — the hook for
changing how the player interacts with the scene without editing the loop. Add a
listener with ``app.on("key_down", fn)`` or as a decorator ``@app.on("key_down")``.

Built-in event types (the list the scaffolding's docs/EVENTS.md tracks):

| Type          | Fired when                         | Fields on the event        |
|---------------|------------------------------------|----------------------------|
| ``update``    | every frame                        | ``dt``                     |
| ``key_down``  | a key is pressed this frame        | ``key``                    |
| ``key_up``    | a key is released                  | ``key``                    |
| ``mouse_move``| the mouse moved (GPU backend)      | ``dx``, ``dy``             |
| ``quit``      | the app is closing                 | —                          |

Every event also carries ``app`` (so a listener can reach the scene, camera, HUD)
and ``input`` (the current InputState).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

#: the event types the engine fires (kept in sync with docs/EVENTS.md)
EVENT_TYPES = ("update", "key_down", "key_up", "mouse_move", "quit")


@dataclass
class Event:
    type: str
    app: Any = None
    input: Any = None
    dt: float = 0.0
    key: str | None = None
    dx: float = 0.0
    dy: float = 0.0


Listener = Callable[[Event], None]


class Events:
    """A tiny event dispatcher: register listeners per type, emit events to them."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = {}

    def on(self, event_type: str, callback: Listener | None = None):
        """Register a listener. Usable directly — ``events.on("key_down", fn)`` —
        or as a decorator — ``@events.on("key_down")``."""
        if callback is None:
            def decorator(fn: Listener) -> Listener:
                self._listeners.setdefault(event_type, []).append(fn)
                return fn
            return decorator
        self._listeners.setdefault(event_type, []).append(callback)
        return callback

    def off(self, event_type: str, callback: Listener) -> None:
        listeners = self._listeners.get(event_type)
        if listeners and callback in listeners:
            listeners.remove(callback)

    def emit(self, event: Event) -> None:
        for callback in self._listeners.get(event.type, ()):
            callback(event)
