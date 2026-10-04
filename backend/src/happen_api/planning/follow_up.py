"""Choose the single essential question a brief still needs."""

from __future__ import annotations

from happen_api.planning.contracts import (
    Ambiguity,
    BriefField,
    EssentialField,
    FollowUp,
    MissingField,
    PlanningBrief,
)

_ORDER = (
    EssentialField.destination,
    EssentialField.date,
    EssentialField.time,
    EssentialField.primary_intent,
)

_FIELD = {
    EssentialField.destination: BriefField.destination,
    EssentialField.date: BriefField.date,
    EssentialField.time: BriefField.time,
    EssentialField.primary_intent: BriefField.primary_intent,
}


def select_follow_up(brief: PlanningBrief) -> FollowUp | None:
    """Return one blocking question, in destination, date, time, then intent order.

    Optional preferences, accessibility, party size, and budget never become the question.
    Non-blocking notes, including activities past the two-stop limit, stay on the brief.
    """

    blocking: dict[BriefField, Ambiguity] = {}
    for item in brief.ambiguities:
        if item.blocking and item.field not in blocking:
            blocking[item.field] = item
    missing = {item.field: item for item in brief.missing_essentials}
    for essential in _ORDER:
        chosen = blocking.get(_FIELD[essential])
        if chosen is not None:
            return chosen
        pending = missing.get(essential)
        if pending is not None:
            return pending
    return None


def question_for(field: EssentialField) -> MissingField:
    """Build the one stable question for a missing essential."""

    questions = {
        EssentialField.destination: "Which place should this evening be in?",
        EssentialField.date: "Which date should this evening be?",
        EssentialField.time: "What time should the evening start?",
        EssentialField.primary_intent: "What should the first stop be?",
    }
    return MissingField(field=field, question=questions[field])
