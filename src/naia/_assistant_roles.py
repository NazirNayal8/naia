"""User-confirmed assistant responsibilities; no agent invocation or authority grants."""
from __future__ import annotations

import copy

from .storage import NAIAError


ROLE_PRESETS = ("peers", "codex-lead", "claude-lead")
ROLE_QUESTION = {
    "field": "assistant_roles",
    "question": "Would you like to give Codex and Claude different roles and boundaries, or keep them as peers?",
    "options": [*ROLE_PRESETS, "custom"],
    "optional": True,
    "assistant_action": "Ask the user, explain any proposed responsibilities/boundaries, and record only their confirmed choice. For custom roles, clarify each assistant's responsibilities and limits. Use naia instructions roles; never infer a hierarchy from assistant names. Existing role instructions are evidence to confirm, not permission to overwrite them.",
}


def _text(value, field, limit=500):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(token in value for token in ("<!-- naia:", "<!-- /naia:",
                                                "<!-- research-workbench:", "<!-- /research-workbench:"))):
        raise NAIAError(f"{field} must be a nonempty, bounded single line without instruction markers")
    return value.strip()


def validate_assignments(assignments):
    if not isinstance(assignments, dict) or set(assignments) != {"codex", "claude"}:
        raise NAIAError("Custom roles require exactly codex and claude assignments")
    result = {}
    for assistant, entry in assignments.items():
        if not isinstance(entry, dict) or set(entry) != {"role", "responsibilities", "boundaries"}:
            raise NAIAError(f"{assistant} requires role, responsibilities and boundaries")
        normalized = {"role": _text(entry["role"], f"{assistant}.role", 80)}
        for field in ("responsibilities", "boundaries"):
            values = entry[field]
            if not isinstance(values, list) or not 1 <= len(values) <= 12:
                raise NAIAError(f"{assistant}.{field} must contain 1–12 concise entries")
            normalized[field] = [_text(value, f"{assistant}.{field}") for value in values]
        result[assistant] = normalized
    return result


def preset_assignments(preset):
    if not isinstance(preset, str) or preset not in ROLE_PRESETS:
        raise NAIAError("Choose peers, codex-lead or claude-lead, or provide custom assignments")
    peer = {"role": "Peer", "responsibilities": ["Share project work through explicitly assigned NAIA tasks."],
            "boundaries": ["Neither assistant supervises the other; coordinate before overlapping edits."]}
    if preset == "peers":
        return {"codex": copy.deepcopy(peer), "claude": copy.deepcopy(peer)}
    lead = "codex" if preset == "codex-lead" else "claude"
    support = "claude" if lead == "codex" else "codex"
    return {
        lead: {"role": "Lead", "responsibilities": [
            "Lead design and substantive implementation within user-approved scope.",
            "Assign clear support tasks and review their evidence before integrating changes."],
            "boundaries": ["The user retains final approval; a lead role does not authorize launches, destructive work or scope expansion."]},
        support: {"role": "Support", "responsibilities": [
            "Carry out assigned implementation, evaluation, diagnosis and analysis tasks.",
            "Record evidence, results and blockers in shared NAIA records for lead/user review."],
            "boundaries": ["Propose major design changes to the lead/user rather than making them independently.",
                           "Stay within the assigned task and coordinate before editing work owned by the lead."]},
    }


def role_record(*, preset=None, assignments=None, actor=None):
    actor = _text(actor, "Role confirmation requires a named user", 120)
    if (preset is None) == (assignments is None):
        raise NAIAError("Choose a preset or custom assignments, not both")
    roles = preset_assignments(preset) if preset is not None else validate_assignments(assignments)
    return {"preset": preset if preset is not None else "custom", "assignments": roles,
            "confirmed": True, "confirmed_by": actor}


def confirmed_roles(state):
    roles = state.get("roles")
    if roles is None:
        return None
    if not isinstance(roles, dict) or roles.get("confirmed") is not True:
        raise NAIAError("Stored assistant roles must be explicitly confirmed")
    preset = roles.get("preset")
    if not isinstance(preset, str) or preset not in (*ROLE_PRESETS, "custom"):
        raise NAIAError("Invalid stored assistant role preset")
    assignments = validate_assignments(roles.get("assignments"))
    _text(roles.get("confirmed_by"), "Stored role confirmation", 120)
    if preset != "custom" and assignments != preset_assignments(preset):
        raise NAIAError("Stored role assignments do not match their preset")
    return roles


def role_question(state):
    if state.get("selection") != "both":
        return None
    roles = confirmed_roles(state)
    return {**copy.deepcopy(ROLE_QUESTION),
            "answer": {"confirmed": roles is not None, "value": copy.deepcopy(roles)},
            "mode": "confirmed" if roles is not None else "missing"}


def role_section(filename, state):
    if state.get("selection") != "both":
        return ""
    roles = confirmed_roles(state)
    heading = "\n## Assistant roles\n\n"
    if roles is None:
        return heading + ("A role split has not been confirmed. Ask the optional `assistant_roles` onboarding question; "
                          "do not assume either assistant is the lead. Record a confirmed peer choice to avoid asking again.\n")
    assistant = "codex" if filename == "AGENTS.md" else "claude"
    other = "claude" if assistant == "codex" else "codex"
    own = roles["assignments"][assistant]
    lines = [f"- You are {assistant.title()}: {own['role']}.",
             f"- {other.title()}'s confirmed role: {roles['assignments'][other]['role']}."]
    lines.extend(f"- Responsibility: {value}" for value in own["responsibilities"])
    lines.extend(f"- Boundary: {value}" for value in own["boundaries"])
    lines.extend([
        "- These roles apply only while `.lab/project.json` selects both assistants and confirms this assignment; follow its current record if it changes.",
        "- User approval and existing project rules remain authoritative. Roles do not grant permission to launch, delete, publish or expand scope.",
        "- Coordinate through shared NAIA task ownership; do not overwrite another assistant's in-progress work. Role assignment does not automatically run or message the other assistant.",
    ])
    return heading + "\n".join(lines) + "\n"
