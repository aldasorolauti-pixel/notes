"""
P4 Phase 4 (partial) — Rehydration.

Replaces markers like {{PERSON_1}} with original values from the token map.
For now provides both string-level and field-level replacement.
"""

import re

MARKER_RE = re.compile(r"\{\{[A-Z_]+_\d+\}\}")


def rehydrate_text(text: str, token_map: dict[str, str]) -> str:
    """Replace all markers in a plain string with their original values."""
    for marker, original in token_map.items():
        variants = getattr(token_map, "case_variants", {}).get(marker)
        if variants:
            iterator = iter(variants)
            text = re.sub(re.escape(marker), lambda _: next(iterator, original), text)
        else:
            text = text.replace(marker, original)
    return text


def rehydrate(obj, token_map: dict[str, str]):
    """
    Replace markers field-by-field in a dict/list structure (JSON-like).

    This avoids replacing inside the serialized JSON string, which could
    break its structure. Walks the object recursively.
    """
    if isinstance(obj, str):
        return rehydrate_text(obj, token_map)
    elif isinstance(obj, dict):
        return {k: rehydrate(v, token_map) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [rehydrate(item, token_map) for item in obj]
    else:
        return obj
