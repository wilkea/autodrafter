"""Catalogul de eroi: încarcă data/heroes.json și oferă indexare rapidă."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CDN = "https://cdn.cloudflare.steamstatic.com"


@dataclass(frozen=True)
class Hero:
    idx: int           # indice intern 0..n-1, folosit în matrice
    hero_id: int       # id-ul oficial Dota 2
    key: str           # ex. "antimage"
    name: str          # ex. "Anti-Mage"
    attr: str          # str | agi | int | all
    roles: tuple[str, ...]
    img: str


class HeroCatalog:
    """Lista eroilor activi în Captain's Mode, cu indici interni stabili."""

    def __init__(self, heroes: list[Hero]):
        self.heroes = heroes
        self.by_idx = {h.idx: h for h in heroes}
        self.by_id = {h.hero_id: h for h in heroes}
        self.by_key = {h.key: h for h in heroes}

    def __len__(self) -> int:
        return len(self.heroes)

    def __iter__(self):
        return iter(self.heroes)

    def to_json(self) -> list[dict]:
        return [
            {
                "idx": h.idx,
                "id": h.hero_id,
                "key": h.key,
                "name": h.name,
                "attr": h.attr,
                "roles": list(h.roles),
                "img": h.img,
            }
            for h in self.heroes
        ]


@lru_cache(maxsize=1)
def load_catalog(path: Path | None = None) -> HeroCatalog:
    raw = json.loads((path or DATA_DIR / "heroes.json").read_text(encoding="utf-8"))
    rows = sorted(raw.values(), key=lambda h: h["id"])
    heroes: list[Hero] = []
    for h in rows:
        # cm_enabled lipsește uneori pentru eroi foarte noi; îi includem implicit.
        if h.get("cm_enabled") is False:
            continue
        key = h["name"].replace("npc_dota_hero_", "")
        heroes.append(
            Hero(
                idx=len(heroes),
                hero_id=h["id"],
                key=key,
                name=h.get("localized_name") or key,
                attr=h.get("primary_attr") or "all",
                roles=tuple(h.get("roles") or ()),
                img=CDN + (h.get("img") or "").rstrip("?"),
            )
        )
    return HeroCatalog(heroes)
