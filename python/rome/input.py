"""Input, surfaced uniformly to the game regardless of backend.

A backend fills an ``InputState`` each frame. `held` is every key currently
down; `pressed` is the keys that went down *this* frame (edge). Letter keys are
lowercase single characters; a few named keys are spelled out ("escape").
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InputState:
    held: frozenset[str] = field(default_factory=frozenset)
    pressed: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def empty(cls) -> "InputState":
        return cls(frozenset(), frozenset())

    def down(self, key: str) -> bool:
        """Is `key` currently held?"""
        return key in self.held

    def just_pressed(self, key: str) -> bool:
        """Did `key` go down this frame?"""
        return key in self.pressed
