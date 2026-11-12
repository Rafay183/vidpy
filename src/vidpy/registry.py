"""Shared plugin registry for video effects, audio effects and transitions.

Every effect is described by a schema (its params) and a builder that turns
param values into an FFmpeg filter chain. The web studio renders its controls
straight from these schemas, so a newly registered effect appears in the UI
automatically:

    import vidpy

    @vidpy.effect("my_glow", "My Glow", category="Stylize",
                  params=[vidpy.Param("strength", "float", 0.5, 0, 1)])
    def my_glow(p, ctx):
        return f"gblur=sigma={p['strength'] * 10}"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import ffmpeg


@dataclass
class Param:
    name: str
    type: str = "float"  # float | int | bool | color | choice | text | file
    default: Any = 0
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list] = None
    label: str = ""

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v is not None}
        d["label"] = self.label or self.name.replace("_", " ").title()
        return d

    def coerce(self, v: Any) -> Any:
        if v is None:
            return self.default
        try:
            if self.type == "float":
                v = float(v)
            elif self.type == "int":
                v = int(round(float(v)))
            elif self.type == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif self.type == "choice":
                v = str(v)
                if self.choices and v not in [str(c) for c in self.choices]:
                    return self.default
                return v
            else:
                return str(v)
        except (TypeError, ValueError):
            return self.default
        if self.type in ("float", "int"):
            if self.min is not None:
                v = max(v, type(v)(self.min))
            if self.max is not None:
                v = min(v, type(v)(self.max))
        return v


@dataclass
class Effect:
    id: str
    name: str
    kind: str  # video | audio
    category: str
    builder: Callable[[dict, dict], str]
    params: list[Param] = field(default_factory=list)
    description: str = ""
    requires: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return all(ffmpeg.has_filter(r) for r in self.requires)

    def resolve(self, values: dict | None) -> dict:
        values = values or {}
        return {p.name: p.coerce(values.get(p.name)) for p in self.params}

    def build(self, values: dict | None = None, ctx: dict | None = None) -> str:
        return self.builder(self.resolve(values), ctx or {})

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "category": self.category,
                "description": self.description, "available": self.available,
                "params": [p.to_dict() for p in self.params]}


VIDEO_EFFECTS: dict[str, Effect] = {}
AUDIO_EFFECTS: dict[str, Effect] = {}


def _register(table: dict, kind: str, id: str, name: str, category: str, params=None,
              description: str = "", requires=None):
    def deco(fn):
        table[id] = Effect(id=id, name=name, kind=kind, category=category, builder=fn,
                           params=list(params or []), description=description,
                           requires=list(requires or []))
        return fn
    return deco


def effect(id: str, name: str, category: str = "Custom", params=None, description: str = "",
           requires=None):
    """Register a video effect (decorator)."""
    return _register(VIDEO_EFFECTS, "video", id, name, category, params, description, requires)


def audio_effect(id: str, name: str, category: str = "Custom", params=None, description: str = "",
                 requires=None):
    """Register an audio effect (decorator)."""
    return _register(AUDIO_EFFECTS, "audio", id, name, category, params, description, requires)


def get_effect(id: str, kind: str = "video") -> Effect:
    table = VIDEO_EFFECTS if kind == "video" else AUDIO_EFFECTS
    if id not in table:
        raise KeyError(f"Unknown {kind} effect '{id}'. Try vidpy.list_effects('{kind}').")
    return table[id]


def list_effects(kind: str = "video") -> list[dict]:
    table = VIDEO_EFFECTS if kind == "video" else AUDIO_EFFECTS
    return [e.to_dict() for e in table.values()]
