"""
Tests for P4 Phase 1 — Sanitization.

Covers:
  - No entity leaks in masked text
  - Dates/deadlines preserved
  - Deterministic output
  - Round-trip (mask → rehydrate = original)
  - Marker format validation
"""

import re
from pathlib import Path
import pytest

# Resolve paths relative to repo root
ROOT = Path(__file__).resolve().parent.parent
ENTITIES_PATH = ROOT / "data" / "entities.json"
NICKNAMES_PATH = ROOT / "data" / "nicknames.json"
SAMPLES_DIR = ROOT / "samples"

from p4.sanitize import Sanitizer, load_entities, MARKER_RE
from p4.rehydrate import rehydrate, rehydrate_text


@pytest.fixture(scope="module")
def sanitizer():
    return Sanitizer(ENTITIES_PATH, NICKNAMES_PATH)


@pytest.fixture(scope="module")
def entities():
    return load_entities(ENTITIES_PATH)


@pytest.fixture(scope="module")
def sample_notes():
    """Load all three sample notes."""
    notes = {}
    for f in sorted(SAMPLES_DIR.glob("notes_*.txt")):
        notes[f.stem] = f.read_text(encoding="utf-8")
    return notes


# ---------- No leaks ----------

def _all_entity_names(entities: dict) -> list[str]:
    """Extract every name/alias from entities.json."""
    names = []
    for person in entities.get("people", []):
        names.append(person["full_name"])
        names.extend(person.get("aliases", []))
    for org in entities.get("orgs", []):
        names.append(org["name"])
        names.extend(org.get("aliases", []))
    return names


class TestNoLeaks:
    """No original entity value should appear in the masked text."""

    def test_clear_notes(self, sanitizer, entities, sample_notes):
        masked, _ = sanitizer.mask(sample_notes["notes_01_clear"])
        for name in _all_entity_names(entities):
            assert name not in masked, f"Leaked: '{name}'"

    def test_messy_notes(self, sanitizer, entities, sample_notes):
        masked, _ = sanitizer.mask(sample_notes["notes_02_messy"])
        for name in _all_entity_names(entities):
            # Case-insensitive check for messy notes
            assert name.lower() not in masked.lower(), f"Leaked: '{name}'"

    def test_vague_notes(self, sanitizer, entities, sample_notes):
        masked, _ = sanitizer.mask(sample_notes["notes_03_vague"])
        for name in _all_entity_names(entities):
            assert name not in masked, f"Leaked: '{name}'"


# ---------- Dates preserved ----------

class TestDatesPreserved:
    """Dates and deadlines must NOT be masked."""

    def test_friday_preserved(self, sanitizer):
        text = "Mike will send drawings by Friday."
        masked, _ = sanitizer.mask(text)
        assert "Friday" in masked

    def test_march_date_preserved(self, sanitizer):
        text = "Jenny will confirm by March 20."
        masked, _ = sanitizer.mask(text)
        assert "March 20" in masked

    def test_vague_timing_preserved(self, sanitizer):
        text = "We need to get the drawings out sometime next week-ish."
        masked, _ = sanitizer.mask(text)
        assert "next week-ish" in masked

    def test_relative_day_preserved(self, sanitizer):
        text = "Acme delivery moved, will know more thurs."
        masked, _ = sanitizer.mask(text)
        assert "thurs" in masked


# ---------- Deterministic ----------

class TestDeterministic:
    """Calling mask() twice on the same text must give the same result."""

    def test_same_output(self, sanitizer, sample_notes):
        for name, text in sample_notes.items():
            m1, map1 = sanitizer.mask(text)
            m2, map2 = sanitizer.mask(text)
            assert m1 == m2, f"Non-deterministic masked text for {name}"
            assert map1 == map2, f"Non-deterministic token map for {name}"


# ---------- Round-trip ----------

class TestRoundTrip:
    """mask() → rehydrate() must recover the original text."""

    def test_roundtrip_all_samples(self, sanitizer, sample_notes):
        for name, text in sample_notes.items():
            masked, token_map = sanitizer.mask(text)
            restored = rehydrate_text(masked, token_map)
            assert restored == text, f"Round-trip failed for {name}"

    def test_roundtrip_with_email_and_phone(self, sanitizer):
        text = "Call Jenny at (415) 555-0134 or jenny.ortiz@example.invalid."
        masked, token_map = sanitizer.mask(text)
        restored = rehydrate_text(masked, token_map)
        assert restored == text

    def test_evidence_rehydrates_alias_using_original_occurrence(self, sanitizer):
        text = "Ana Pérez: Ana confirma el cambio."
        masked, token_map = sanitizer.mask(text, participants=["Ana"])
        masked_evidence = masked.split(": ", 1)[1]
        result = rehydrate(
            {"evidence": masked_evidence, "owner_evidence": masked_evidence},
            token_map,
        )
        assert result["evidence"] == "Ana confirma el cambio."
        assert result["owner_evidence"] == "Ana confirma el cambio."


# ---------- Marker format ----------

class TestMarkerFormat:
    """All markers in the output must match {{TYPE_N}} pattern."""

    def test_markers_valid(self, sanitizer, sample_notes):
        for name, text in sample_notes.items():
            masked, _ = sanitizer.mask(text)
            # Find anything that looks like it could be a marker
            braces = re.findall(r"\{\{.*?\}\}", masked)
            for m in braces:
                assert MARKER_RE.fullmatch(m), f"Bad marker format: {m} in {name}"


class TestBilingualRoster:
    def test_spanish_roster_name_masks_following_surname_in_speaker_label(self, sanitizer):
        text = "Irene: Irene Valdés presenta el avance. Irene confirma el plazo."
        masked, token_map = sanitizer.mask(text, participants=["Irene"])
        assert "Irene" not in masked
        assert "Valdés" not in masked
        assert any("Irene Valdés" in aliases for aliases in sanitizer.last_diagnostics["aliases"])
        assert len([marker for marker in token_map if "PERSON" in marker]) == 1

    def test_english_roster_name_masks_two_following_name_tokens(self, sanitizer):
        text = "Morgan: Morgan Reed Taylor reviews the draft. Morgan sends it tomorrow."
        masked, token_map = sanitizer.mask(text, participants=["Morgan"])
        assert "Morgan" not in masked
        assert "Reed" not in masked
        assert "Taylor" not in masked
        assert any("Morgan Reed Taylor" in aliases for aliases in sanitizer.last_diagnostics["aliases"])
        assert len([marker for marker in token_map if "PERSON" in marker]) == 1

    def test_roster_does_not_include_catalog_without_text_evidence(self, sanitizer):
        _, _ = sanitizer.mask("La reunión trata sobre el calendario del proyecto.")
        assert sanitizer.last_diagnostics["roster"] == {}

    def test_spanish_common_words_and_phrases_are_not_persons(self, sanitizer):
        text = "Lo entiendo. Dale, movemos el release y lo movamos al 20 para el seguimiento."
        masked, token_map = sanitizer.mask(text)
        assert masked == text
        assert not any("PERSON" in marker for marker in token_map)

    def test_roster_masks_all_case_and_accent_variants(self, sanitizer):
        text = (
            "N\u00edcolas: Hola Nico, gracias N\u00edcolas. Nico confirma el plan. "
            "Esteban, you send it. ESTEBAN will follow up."
        )
        masked, token_map = sanitizer.mask(text, participants=["N\u00edcolas", "Nico", "Esteban"])
        assert "N\u00edcolas" not in masked
        assert "Nico" not in masked
        assert "ESTEBAN" not in masked
        assert len([marker for marker in token_map if "PERSON" in marker]) == 2

    def test_english_roster_masks_repeated_names(self, sanitizer):
        text = "Jordan: Hello Jo. Thanks Jordan. Jo will confirm it; JORDAN will send it."
        masked, token_map = sanitizer.mask(text, participants=["Jordan", "Jo"])
        assert "Jordan" not in masked
        assert "Jo" not in masked
        assert len([marker for marker in token_map if "PERSON" in marker]) == 1

    def test_attendee_list_is_split_and_applied_globally(self, sanitizer):
        text = "Estamos Alba, Bruno, Ciro y yo. Alba coordina. Bruno revisa. Ciro confirma con Alba."
        masked, _ = sanitizer.mask(text)
        assert all(name not in masked for name in ("Alba", "Bruno", "Ciro"))
        assert "Estamos" in masked
        assert not sanitizer.last_diagnostics["residue_failures"]

    def test_vocative_only_name_is_added_to_roster(self, sanitizer):
        text = "Hola Dalia, ¿podés mirar esto? Dalia responde después."
        masked, _ = sanitizer.mask(text)
        assert masked.count("{{PERSON_") == 2
        assert not sanitizer.last_diagnostics["residue_failures"]

    def test_common_sentence_starters_are_not_persons(self, sanitizer):
        text = "Dejá el informe listo. Listo, seguimos. Quién confirma? quien pueda avisa."
        masked, token_map = sanitizer.mask(text)
        assert masked == text
        assert not any("PERSON" in marker for marker in token_map)

    def test_aliases_share_one_marker_and_cover_all_occurrences(self, sanitizer):
        text = "Rafa y Rafael participan. Rafa presenta; Rafael envía."
        masked, token_map = sanitizer.mask(text, participants=["Rafael", "Rafa"])
        person_markers = [marker for marker in token_map if "PERSON" in marker]
        assert len(person_markers) == 1
        assert "Rafa" not in masked and "Rafael" not in masked

    def test_vocative_aliases_share_marker(self, sanitizer):
        text = "Nicolás, ¿cómo venís? Nico confirma después."
        masked, token_map = sanitizer.mask(text)
        person_markers = [marker for marker in token_map if "PERSON" in marker]
        assert len(person_markers) == 1
        assert "Nicolás" not in masked and "Nico" not in masked

    def test_english_common_openers_are_unchanged(self, sanitizer):
        text = (
            "Perfect, we can start. Great, the plan sounds good. Right now we can proceed. "
            "Okay, that works. Alright, let's continue. Good, noted. Excellent. "
            "Oh, hey, oof, that is unexpected."
        )
        masked, token_map = sanitizer.mask(text)
        assert masked == text
        assert not any(marker.startswith("{{PERSON_") for marker in token_map)
