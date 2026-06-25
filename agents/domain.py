"""SWaT (Secure Water Treatment) process knowledge.

The testbed is a 6-stage water treatment plant. Tag naming encodes the stage
in the first digit (FIT101 -> stage 1, AIT201 -> stage 2, P602 -> stage 6),
which lets us map a deviating sensor to its physical subsystem and reason about
downstream blast radius.
"""

from __future__ import annotations

import re

STAGE_DESC: dict[int, str] = {
    1: "Raw water intake & supply",
    2: "Chemical dosing / pre-treatment",
    3: "Ultrafiltration (UF)",
    4: "Dechlorination (UV + bisulphite)",
    5: "Reverse osmosis (RO)",
    6: "RO permeate transfer & UF backwash",
}

# Process flow is sequential: a compromise at stage N threatens N, N+1, ...
DOWNSTREAM = {s: [d for d in range(s, 7)] for s in range(1, 7)}


def stage_of(tag: str) -> int:
    """Stage number (1-6) encoded in a SWaT tag, or 0 if not parseable."""
    m = re.search(r"\d", tag or "")
    return int(m.group(0)) if m else 0


def stage_label(tag_or_stage) -> str:
    s = tag_or_stage if isinstance(tag_or_stage, int) else stage_of(tag_or_stage)
    return f"Stage {s} ({STAGE_DESC.get(s, 'unknown')})" if s else "unknown"


def subsystems_for(tags: list[str]) -> list[str]:
    """Unique stage labels touched by a list of component tags, in order."""
    stages = sorted({stage_of(t) for t in tags if stage_of(t)})
    return [f"Stage {s} ({STAGE_DESC[s]})" for s in stages if s in STAGE_DESC]


def blast_radius_for(tags: list[str]) -> str:
    """Human description of downstream impact from the earliest affected stage."""
    stages = sorted({stage_of(t) for t in tags if stage_of(t)})
    if not stages:
        return "Unknown — no subsystem attribution"
    first = stages[0]
    affected = DOWNSTREAM[first]
    if len(affected) == 1:
        return f"Contained to Stage {first} ({STAGE_DESC[first]})"
    return (
        f"Stage {first} ({STAGE_DESC[first]}) with downstream risk to stages "
        f"{', '.join(str(s) for s in affected[1:])}"
    )


# Compact reference block injected into LLM prompts.
PROCESS_CONTEXT = "\n".join(
    f"  Stage {s}: {d}" for s, d in STAGE_DESC.items()
)
