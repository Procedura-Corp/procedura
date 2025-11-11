# procedura_sdk/modules/init_character.py
# -----------------------------------------------------------------------------
# Encapsulated helper for "init_character" that mirrors the UI panel behavior
# WITHOUT modifying RemoteAgent or the top-level CLI.
#
# Usage (Python):
#   from procedura_sdk import RemoteAgent
#   from procedura_sdk.modules.init_character import run_init_character
#
#   ra = RemoteAgent("ws://127.0.0.1:8765")
#   out = run_init_character(
#       ra,
#       role_id="explorer",
#       sub_id="cartographer",
#       roles_url=None,  # or point at JSON/URL
#       objective_text=None,  # auto-build if omitted
#       gen_occ="all:4",
#   )
#
# CLI (no API changes required):
#   python -m procedura_sdk.modules.init_character \
#       --url ws://127.0.0.1:8765 \
#       --role-id explorer \
#       --sub-id cartographer
#
# Or provide prebuilt guidance/objective directly:
#   python -m procedura_sdk.modules.init_character \
#       --url ws://127.0.0.1:8765 \
#       --gen-guidance 'favor explorer (explorer) | sub:cartographer (cartographer) | ...' \
#       --objective-text 'Explorer/Cartographer: ...'
#
# Pass-through flags after '--' are appended verbatim to the module call.
# -----------------------------------------------------------------------------

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Import the existing SDK API (unchanged)
from procedura_sdk.remote_agent import RemoteAgent

# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────

Trait = str

@dataclass
class SubArchetype:
    id: str
    display_name: str
    description: str
    extra_traits: List[Trait] = field(default_factory=list)

@dataclass
class Role:
    role_id: str
    display_name: str
    focus: str
    presence_footprint: str
    traits: List[Trait]
    narrative_levers: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    seed_hooks: Dict[str, Any] = field(default_factory=dict)
    lattice_modifiers: Dict[str, float] = field(default_factory=dict)
    encounter_bias: Dict[str, float] = field(default_factory=dict)
    sub_archetypes: List[SubArchetype] = field(default_factory=list)

@dataclass
class RolesPayload:
    version: str
    roles: List[Role]

# ─────────────────────────────────────────────────────────────────────────────
# Fallback roles (minimal), mirrors the panel fallback
# ─────────────────────────────────────────────────────────────────────────────

FALLBACK_ROLES: List[Role] = [
    Role(
        role_id="combatant",
        display_name="Combatant",
        focus="Direct confrontation, skirmishes, faction warfare, survival through force.",
        presence_footprint="Raises spawn pressure; attracts hostile encounters.",
        traits=["weapon_skill", "endurance", "tactics", "intimidation"],
        sub_archetypes=[
            SubArchetype(id="frontliner", display_name="Frontliner", description="Heavy weapons, armor, suppression."),
            SubArchetype(id="raider",     display_name="Raider",     description="Opportunistic; mobile scavenging."),
            SubArchetype(id="scout",      display_name="Scout",      description="Recon, ranged, tracking."),
        ],
    ),
    Role(
        role_id="explorer",
        display_name="Explorer",
        focus="Discovery, maps, lore, uncovering buried sites.",
        presence_footprint="Raises exploration heat; unlocks new tiles.",
        traits=["cartography", "navigation", "archaeology", "resource_scouting"],
        sub_archetypes=[
            SubArchetype(id="nomad",        display_name="Nomad",        description="Adaptable survival on the move."),
            SubArchetype(id="cartographer", display_name="Cartographer", description="Creates maps; reveals structure."),
            SubArchetype(id="prospector",   display_name="Prospector",   description="Hunts rare minerals and artifacts."),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# Roles loading (override → local-ish → remote → fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))

def _parse_roles_payload(payload: dict) -> List[Role]:
    roles_data = payload.get("roles") or []
    out: List[Role] = []
    for r in roles_data:
        subs = [
            SubArchetype(
                id=s.get("id", ""),
                display_name=s.get("display_name", ""),
                description=s.get("description", ""),
                extra_traits=list(s.get("extra_traits") or []),
            )
            for s in (r.get("sub_archetypes") or [])
        ]
        out.append(
            Role(
                role_id=r.get("role_id", ""),
                display_name=r.get("display_name", ""),
                focus=r.get("focus", ""),
                presence_footprint=r.get("presence_footprint", ""),
                traits=list(r.get("traits") or []),
                narrative_levers=list(r.get("narrative_levers") or []),
                tags=list(r.get("tags") or []),
                seed_hooks=dict(r.get("seed_hooks") or {}),
                lattice_modifiers=dict(r.get("lattice_modifiers") or {}),
                encounter_bias=dict(r.get("encounter_bias") or {}),
                sub_archetypes=subs,
            )
        )
    return out

def load_roles(override_url: Optional[str] = None) -> List[Role]:
    """
    Attempts to load roles in this order:
      1) override_url (if provided)
      2) /kb/mechanics/roles_types.json
      3) /sn/roles_types.json
      4) https://procedura.org/static/scorched_nebraska_kb/mechanics/roles_types.json
      5) FALLBACK_ROLES
    """
    candidates = [override_url] if override_url else []
    candidates += [
        "/kb/mechanics/roles_types.json",
        "/sn/roles_types.json",
        "https://procedura.org/static/scorched_nebraska_kb/mechanics/roles_types.json",
    ]

    for url in candidates:
        try:
            data = _http_get_json(url)
            roles = _parse_roles_payload(data)
            if roles:
                return roles
        except Exception:
            continue

    # Fallback
    return FALLBACK_ROLES

# ─────────────────────────────────────────────────────────────────────────────
# Public helper: build guidance/objective directly from a JSON source
# ─────────────────────────────────────────────────────────────────────────────

def load_roles_from_path_or_url(path_or_url: str) -> List[Role]:
    """
    If 'path_or_url' looks like a local path and exists, read from disk.
    Otherwise treat it as a URL and fetch over HTTP(S).
    """
    if os.path.exists(path_or_url):
        with open(path_or_url, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = _http_get_json(path_or_url)
    return _parse_roles_payload(data)

def build_guidance_from_json(path_or_url: str, role_id: str, sub_id: str) -> str:
    """
    Convenience: build the exact guidance string used by the UI,
    using roles JSON from a file/URL.
    """
    roles = load_roles_from_path_or_url(path_or_url)
    role, sub = pick_role_and_sub(roles, role_id, sub_id)
    return build_guidance(role, sub)

def build_objective_from_json(path_or_url: str, role_id: str, sub_id: str) -> str:
    """
    Convenience: build the objective line used by the UI,
    using roles JSON from a file/URL.
    """
    roles = load_roles_from_path_or_url(path_or_url)
    role, sub = pick_role_and_sub(roles, role_id, sub_id)
    return build_objective(role, sub)

# ─────────────────────────────────────────────────────────────────────────────
# Guidance & objective builders (parity with the panel)
# ─────────────────────────────────────────────────────────────────────────────

def build_guidance(role: Role, sub: SubArchetype) -> str:
    traits = (role.traits or [])[:6]
    tags   = (role.tags or [])[:4]
    levers = (role.narrative_levers or [])[:3]
    extras = (sub.extra_traits or [])[:3]

    parts: List[str] = []
    parts.append(f"favor {role.display_name.lower()} ({role.role_id})")
    parts.append(f"sub:{sub.display_name.lower()} ({sub.id})")
    if role.focus:
        parts.append(f"focus:{role.focus}")
    if role.presence_footprint:
        parts.append(f"presence:{role.presence_footprint}")
    if traits:
        parts.append("traits:" + ",".join(traits))
    if extras:
        parts.append("extra:" + ",".join(extras))
    if tags:
        parts.append("tags:" + ",".join(tags))
    if levers:
        parts.append("levers:" + ",".join(levers))
    return " | ".join(parts)

_BASE_OBJECTIVES: Dict[str, str] = {
    "combatant": "Stay mobile; avoid overcommitment; conserve ammo; check exits.",
    "support":   "Stabilize allies; prioritize rescue/triage; avoid overexposure.",
    "merchant":  "Probe barter routes; avoid hotspots; secure safe exchanges.",
    "builder":   "Anchor footholds; prefer defensible ground; stage materials.",
    "explorer":  "Map edges; log points of interest; avoid unstable ruins.",
    "diplomat":  "De-escalate; open channels; avoid needless hostilities.",
    "outlaw":    "Minimize signatures; strike surgically; avoid settlements.",
    "wanderer":  "Keep low profile; document findings; avoid crowded zones.",
}

def build_objective(role: Role, sub: SubArchetype) -> str:
    base = _BASE_OBJECTIVES.get(role.role_id, "Prioritize mapping and intel. Keep risk low.")
    return f"{role.display_name}/{sub.display_name}: {base} Hydrate; work 6–8 hours."

# ─────────────────────────────────────────────────────────────────────────────
# Selection helpers
# ─────────────────────────────────────────────────────────────────────────────

def pick_role_and_sub(roles: List[Role], role_id: str, sub_id: str) -> Tuple[Role, SubArchetype]:
    role = next((r for r in roles if r.role_id == role_id), None)
    if not role:
        raise ValueError(f"Role '{role_id}' not found")
    sub = next((s for s in role.sub_archetypes if s.id == sub_id), None)
    if not sub:
        raise ValueError(f"Sub-archetype '{sub_id}' not found for role '{role_id}'")
    return role, sub

# ─────────────────────────────────────────────────────────────────────────────
# Core runners (sync + stream) — DO NOT modify RemoteAgent
# ─────────────────────────────────────────────────────────────────────────────

def run_init_character(
    ra: RemoteAgent,
    *,
    # Path A: compute from role/sub (+ optional roles_url)
    role_id: Optional[str] = None,
    sub_id: Optional[str] = None,
    roles_url: Optional[str] = None,
    # Path B: provide direct strings
    gen_guidance: Optional[str] = None,
    objective_text: Optional[str] = None,
    # Common options
    gen_occ: str = "all:4",
    extra_args: Optional[List[str]] = None,
    ack_timeout: float = 10.0,
    final_timeout: float = 600.0,
) -> Any:
    """
    Synchronous run mirroring the UI's Confirm button.

    Either provide (role_id, sub_id[, roles_url]) OR (gen_guidance[, objective_text]).
    """
    if gen_guidance is None:
        if not (role_id and sub_id):
            raise ValueError("Provide either (gen_guidance) OR (role_id and sub_id)")
        roles = load_roles(roles_url)
        role, sub = pick_role_and_sub(roles, role_id, sub_id)
        gen_guidance = build_guidance(role, sub)
        if objective_text is None:
            objective_text = build_objective(role, sub)

    args: List[str] = [
        f"--gen-guidance={gen_guidance}",
        f"--gen-occ={gen_occ}",
    ]
    if objective_text:
        args.append(f"--objective-text={objective_text}")
    if extra_args:
        args.extend(extra_args)

    return ra.run("init_character", args, ack_timeout=ack_timeout, final_timeout=final_timeout)

async def stream_init_character(
    ra: RemoteAgent,
    *,
    role_id: Optional[str] = None,
    sub_id: Optional[str] = None,
    roles_url: Optional[str] = None,
    gen_guidance: Optional[str] = None,
    objective_text: Optional[str] = None,
    gen_occ: str = "all:4",
    extra_args: Optional[List[str]] = None,
):
    """
    Async streaming run; yields events ('started'/'running'/'finished'/'error').
    """
    if gen_guidance is None:
        if not (role_id and sub_id):
            raise ValueError("Provide either (gen_guidance) OR (role_id and sub_id)")
        roles = load_roles(roles_url)
        role, sub = pick_role_and_sub(roles, role_id, sub_id)
        gen_guidance = build_guidance(role, sub)
        if objective_text is None:
            objective_text = build_objective(role, sub)

    args: List[str] = [
        f"--gen-guidance={gen_guidance}",
        f"--gen-occ={gen_occ}",
    ]
    if objective_text:
        args.append(f"--objective-text={objective_text}")
    if extra_args:
        args.extend(extra_args)

    async for ev in ra.run_async_stream("init_character", args):
        yield ev

# ─────────────────────────────────────────────────────────────────────────────
# Small CLI living inside the module (keeps existing CLI untouched)
# ─────────────────────────────────────────────────────────────────────────────

def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))

def _main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        prog="python -m procedura_sdk.modules.init_character",
        description="Run init_character with UI-parity behavior (no SDK API changes).",
    )
    p.add_argument("--url", default="ws://127.0.0.1:8765", help="ws:// or wss:// server")
    p.add_argument("--token", default=None, help="session token (else ~/.procedura/token)")

    mode = p.add_mutually_exclusive_group(required=True)
    # Path A: compute from role/sub
    mode.add_argument("--role-id", help="Role id (e.g., explorer)")
    p.add_argument("--sub-id", help="Sub-archetype id (e.g., cartographer)")
    p.add_argument("--roles-url", default=None, help="Override roles JSON URL or local path")
    # Path B: direct strings
    mode.add_argument("--gen-guidance", help="Provide prebuilt guidance string directly")
    p.add_argument("--objective-text", default=None, help="Provide objective; if omitted and role/sub used, auto-built")

    p.add_argument("--gen-occ", default="all:4", help='Occurrence (default: "all:4")')
    p.add_argument("--stream", action="store_true", help="Stream events instead of waiting for final result")
    p.add_argument("--ack-timeout", type=float, default=10.0, help="Sync ack timeout (s)")
    p.add_argument("--final-timeout", type=float, default=600.0, help="Sync final timeout (s)")

    # Extra flags after '--' are passed to the module unchanged
    p.add_argument("extra", nargs="*", help="Extra flags appended verbatim; use '--' separator")

    # Helper-only flows (no agent calls)
    p.add_argument("--print-guidance-from", default=None,
                   help="(Helper) Path/URL to roles JSON; prints guidance for --role-id/--sub-id and exits")
    p.add_argument("--print-objective-from", default=None,
                   help="(Helper) Path/URL to roles JSON; prints objective for --role-id/--sub-id and exits")

    args, unknown = p.parse_known_args(argv)
    if unknown and unknown[0] == "--":
        unknown = unknown[1:]
        args.extra = (args.extra or []) + unknown

    # Helper-only modes
    if args.print_guidance_from:
        if not (args.role_id and args.sub_id):
            raise SystemExit("Provide --role-id and --sub-id with --print-guidance-from.")
        s = build_guidance_from_json(args.print_guidance_from, args.role_id, args.sub_id)
        print(s)
        return

    if args.print_objective_from:
        if not (args.role_id and args.sub_id):
            raise SystemExit("Provide --role-id and --sub-id with --print-objective-from.")
        s = build_objective_from_json(args.print_objective_from, args.role_id, args.sub_id)
        print(s)
        return

    try:
        ra = RemoteAgent(args.url, token=args.token)

        if args.stream:
            import asyncio

            async def go():
                if args.gen_guidance:
                    async for ev in stream_init_character(
                        ra,
                        gen_guidance=args.gen_guidance,
                        objective_text=args.objective_text,
                        gen_occ=args.gen_occ,
                        extra_args=args.extra or [],
                    ):
                        _print(ev)
                else:
                    if not (args.role_id and args.sub_id):
                        raise SystemExit("When not using --gen-guidance, both --role-id and --sub-id are required.")
                    async for ev in stream_init_character(
                        ra,
                        role_id=args.role_id,
                        sub_id=args.sub_id,
                        roles_url=args.roles_url,
                        objective_text=args.objective_text,
                        gen_occ=args.gen_occ,
                        extra_args=args.extra or [],
                    ):
                        _print(ev)

            import asyncio as _asyncio
            _asyncio.run(go())
        else:
            if args.gen_guidance:
                out = run_init_character(
                    ra,
                    gen_guidance=args.gen_guidance,
                    objective_text=args.objective_text,
                    gen_occ=args.gen_occ,
                    extra_args=args.extra or [],
                    ack_timeout=args.ack_timeout,
                    final_timeout=args.final_timeout,
                )
            else:
                if not (args.role_id and args.sub_id):
                    raise SystemExit("When not using --gen-guidance, both --role-id and --sub-id are required.")
                out = run_init_character(
                    ra,
                    role_id=args.role_id,
                    sub_id=args.sub_id,
                    roles_url=args.roles_url,
                    objective_text=args.objective_text,
                    gen_occ=args.gen_occ,
                    extra_args=args.extra or [],
                    ack_timeout=args.ack_timeout,
                    final_timeout=args.final_timeout,
                )
            _print(out)
    except Exception as e:
        _print({"status": "error", "message": str(e)})
        raise SystemExit(1)

if __name__ == "__main__":
    _main()

