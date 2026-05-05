"""Rule: slot_loop_no_progress

The same topic re-triggers N times in succession without an intervening
`VariableAssignment` event — typical of a slot-fill question that the user
keeps failing to answer. Severity escalates with N.
"""

from __future__ import annotations

from diagnosis.constraints._helpers import component_ref_for_schema
from diagnosis.models import ConstraintViolation, FailureCategory
from models import BotProfile, ConversationTimeline, EventType


RULE_ID = "slot_loop_no_progress"
SLOT_LOOP_N = 3  # warn threshold
SLOT_LOOP_N_HARD = 5  # critical threshold


def check(profile: BotProfile, timeline: ConversationTimeline) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []

    triggers: dict[str, list[int]] = {}
    last_assignment_pos: dict[str, int] = {}

    for ev in timeline.events:
        if ev.event_type == EventType.STEP_TRIGGERED and ev.topic_name:
            triggers.setdefault(ev.topic_name, []).append(ev.position)
        elif ev.event_type == EventType.VARIABLE_ASSIGNMENT and ev.topic_name:
            last_assignment_pos[ev.topic_name] = ev.position

    for topic_name, positions in triggers.items():
        if len(positions) < SLOT_LOOP_N:
            continue
        # Count consecutive triggers without an assignment in between.
        last_assign = last_assignment_pos.get(topic_name, -1)
        no_progress = [p for p in positions if p > last_assign]
        if len(no_progress) < SLOT_LOOP_N:
            continue
        severity = "critical" if len(no_progress) >= SLOT_LOOP_N_HARD else "warn"
        # Find the matching component for the schema_name lookup.
        schema_name = next(
            (c.schema_name for c in profile.components if c.display_name == topic_name),
            topic_name,
        )
        out.append(
            ConstraintViolation(
                rule_id=RULE_ID,
                step_index=no_progress[-1],
                severity=severity,
                description=(
                    f"Topic '{topic_name}' re-triggered {len(no_progress)} times without a "
                    "variable assignment — the user can't or won't supply the slot value."
                ),
                evidence={
                    "topic_name": topic_name,
                    "trigger_count": len(no_progress),
                    "trigger_positions": no_progress,
                    "last_variable_assignment_position": last_assign if last_assign >= 0 else None,
                },
                component_refs=component_ref_for_schema(profile, schema_name),
                default_category_seed=FailureCategory.UNDERSPECIFIED_INTENT,
            )
        )
    return out
