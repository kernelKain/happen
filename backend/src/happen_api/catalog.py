"""Public allowlists and versions exposed by the metadata endpoint."""

from __future__ import annotations

CONTRACT_VERSION = "1.0.0"
SCORING_POLICY_VERSION = "v1"
TIMEZONE = "Asia/Kolkata"

NEIGHBORHOODS = ("indiranagar",)
CATEGORIES = ("restaurants",)
EXPERIENCES = ("easier_conversation",)
PRIORITIES = ("conversation", "short_wait", "seating")

CANONICAL_PRESET = {
    "neighborhood": "indiranagar",
    "restaurant_category": "restaurants",
    "arrival_start": "18:00",
    "arrival_end": "21:00",
    "desired_experience": "easier_conversation",
    "priorities": list(PRIORITIES),
}

MAX_BODY_BYTES = 16 * 1024
