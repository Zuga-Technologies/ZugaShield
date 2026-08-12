"""Fleet failure_reason contract — The Pentagon's adoption.

Law: docs/fleet/FAILURE_REASON_CONTRACT.md (taxonomy ruled 2026-08-11).
Slug format `<category>: <detail>`, whole slug <= 200 chars. A category may
only come from the ruled list — anything else is preserved as
`unknown: <original>`, never guessed into a category. None stays None
(nobody attempted classification; success rows stay NULL).
"""

CATEGORIES = (
    "capacity", "incomplete", "infrastructure", "quality", "resource",
    "escalation", "unknown", "dependency", "auth", "rate_limit", "budget",
    "input", "internal",
)

MAX_LEN = 200


def normalize(raw: str | None) -> str | None:
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    prefix = raw.split(":", 1)[0].strip().lower()
    if ":" in raw and prefix in CATEGORIES:
        return raw[:MAX_LEN]
    return f"unknown: {raw}"[:MAX_LEN]
