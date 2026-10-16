"""Jurisdiction adapters that emit the national bore / lithology template."""

from __future__ import annotations

from typing import Callable

from . import vic_deeca

AdapterFn = Callable[[dict], tuple[dict[str, dict], list[dict], dict]]

ADAPTERS: dict[str, AdapterFn] = {
    "vic_deeca": vic_deeca.fetch,
}


def get_adapter(name: str) -> AdapterFn:
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        known = ", ".join(sorted(ADAPTERS)) or "(none)"
        raise ValueError(f"Unknown adapter {name!r}. Known: {known}") from exc
