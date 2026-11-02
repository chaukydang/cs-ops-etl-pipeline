"""Public names for skill groups: the report shows the audience and channel, never the group name.

`AUDIENCE_BY_CODE` maps the audience code inside a skill group name (VN-<code>-...) to its label;
change it here if the mapping differs. Channel comes from the TK / IM part of the name.
"""

from __future__ import annotations

import re

AUDIENCE_BY_CODE = {"CR": "Creator", "SS": "Seller", "KAS": "Buyer"}
CHANNEL_BY_CODE = {"TK": "Ticket", "IM": "Chat"}
AUDIENCES = ["Creator", "Seller", "Buyer"]
CHANNELS = ["Chat", "Ticket"]


def audience(skill_group: str) -> str:
    match = re.match(r"^[A-Z]{2}-([A-Z]+)-", skill_group or "")
    return AUDIENCE_BY_CODE.get(match.group(1) if match else "", "Other")


def channel(skill_group: str) -> str:
    match = re.search(r"-(TK|IM)-", skill_group or "")
    return CHANNEL_BY_CODE.get(match.group(1) if match else "", "Other")


def display(skill_group: str) -> str:
    return f"{audience(skill_group)} · {channel(skill_group)}"


def select(groups: list[str], audiences: list[str], channels: list[str]) -> list[str]:
    """Skill groups matching both filters; empty selections mean 'all'."""
    chosen = [
        g for g in groups
        if (not audiences or audience(g) in audiences) and (not channels or channel(g) in channels)
    ]
    # nothing matches: return a name that exists nowhere so the report shows no data instead of everything
    return chosen if chosen or not (audiences or channels) else ["__none__"]
