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


Listener = Callable[..., None]

#: sentinel meaning "no explicit `this` was given" (distinct from this=None)
_NO_THIS = object()


class Events:
    """A tiny event dispatcher: register listeners per type, emit events to them.

    Modelled on JS ``addEventListener``: a listener is called with the event. If
    you pass a second value to ``on`` it's handed to the listener as a second
    argument (a "this"/context), so a lambda can carry state without a closure::

        events.on("key_down", lambda e: e.app.close())            # event only
        events.on("key_down", lambda e, player: player.jump(), player)  # + "this"
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[tuple[Listener, object]]] = {}

    def on(self, event_type: str, callback: Listener | None = None, this: object = _NO_THIS):
        """Register a listener. Direct — ``events.on("key_down", fn)`` — or as a
        decorator — ``@events.on("key_down")``. If ``this`` is given, the listener
        is called as ``fn(event, this)``; otherwise ``fn(event)``."""
        if callback is None:
            def decorator(fn: Listener) -> Listener:
                self._listeners.setdefault(event_type, []).append((fn, this))
                return fn
            return decorator
        self._listeners.setdefault(event_type, []).append((callback, this))
        return callback

    def off(self, event_type: str, callback: Listener) -> None:
        listeners = self._listeners.get(event_type)
        if listeners:
            self._listeners[event_type] = [(cb, t) for cb, t in listeners if cb is not callback]

    def emit(self, event: Event) -> None:
        for callback, this in self._listeners.get(event.type, ()):
            if this is _NO_THIS:
                callback(event)
            else:
                callback(event, this)
