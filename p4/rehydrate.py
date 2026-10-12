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


def _rehydrate_evidence(text: str, token_map: dict[str, str]) -> str:
    """Rehydrate a quoted masked fragment using its source occurrence forms."""
    masked_text = getattr(token_map, "masked_text", None)
    occurrence_variants = getattr(token_map, "occurrence_variants", {})
    if not masked_text or not occurrence_variants:
        return rehydrate_text(text, token_map)

    start = masked_text.find(text)
    if start < 0:
        return rehydrate_text(text, token_map)

    output: list[str] = []
    position = 0
    for match in MARKER_RE.finditer(text):
        output.append(text[position:match.start()])
        marker = match.group()
        occurrence = len(re.findall(re.escape(marker), masked_text[:start + match.start()]))
        variants = occurrence_variants.get(marker, [])
        original = variants[occurrence] if occurrence < len(variants) else token_map[marker]
        output.append(original)
        position = match.end()
    output.append(text[position:])
    return "".join(output)


def rehydrate(obj, token_map: dict[str, str]):
    """
    Replace markers field-by-field in a dict/list structure (JSON-like).

    This avoids replacing inside the serialized JSON string, which could
    break its structure. Walks the object recursively.
    """
    if isinstance(obj, str):
        return rehydrate_text(obj, token_map)
    elif isinstance(obj, dict):
        return {
            k: (
                _rehydrate_evidence(v, token_map)
                if k in {"evidence", "owner_evidence"} and isinstance(v, str)
                else rehydrate(v, token_map)
            )
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [rehydrate(item, token_map) for item in obj]
    else:
        return obj
