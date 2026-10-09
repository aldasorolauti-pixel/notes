import pytest
from p4.extract import apply_guardrails, SecurityError

# Dummy masked text and token map for testing
MASKED_TEXT = "Kickoff, {{PERSON_1}}. {{PERSON_2}} is sending the revised drawings to {{ORG_1}} by Friday. We decided to go with the 2 inch steel stud framing on level 3."
TOKEN_MAP = {
    "{{PERSON_1}}": "Vineta Hotel",
    "{{PERSON_2}}": "Mike",
    "{{ORG_1}}": "Acme"
}
MEETING_DATE = "2026-03-10"

def get_base_json():
    return {
        "meeting": {"title": "Test", "date": "2026-03-10"},
        "decisions": [],
        "actions": [],
        "open_questions": []
    }

class TestGuardrails:

    def test_guardrail_1_evidence_must_exist(self):
        """Action should be completely dropped if the main evidence is fabricated."""
        raw = get_base_json()
        raw["actions"].append({
            "task": "Fake task",
            "owner": "unspecified",
            "owner_evidence": None,
            "due_text": "unspecified",
            "due_date": "unspecified",
            "evidence": "This was never said in the text"
        })
        
        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        assert len(result["actions"]) == 0

    def test_guardrail_2_owner_verification(self):
        """Owner should be downgraded to unspecified if owner_evidence is fabricated or doesn't contain the owner."""
        raw = get_base_json()
        raw["actions"].append({
            "task": "Sending drawings",
            "owner": "{{PERSON_2}}",
            # This evidence is real but DOES NOT contain {{PERSON_2}}
            "owner_evidence": "We decided to go with the 2 inch steel",
            "due_text": "unspecified",
            "due_date": "unspecified",
            "evidence": "{{PERSON_2}} is sending the revised drawings"
        })

        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        act = result["actions"][0]
        # Should be downgraded because the owner evidence didn't match
        assert act["owner"] == "unspecified"
        assert act["owner_evidence"] is None

        # Fix it so it works
        raw["actions"][0]["owner_evidence"] = "{{PERSON_2}} is sending the revised drawings"
        result2 = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        assert result2["actions"][0]["owner"] == "{{PERSON_2}}"

    def test_guardrail_3_and_4_date_verification(self):
        """If due_text exists but is hallucinated, fallback to unspecified. Valid dates should parse."""
        raw = get_base_json()
        raw["actions"].append({
            "task": "Sending drawings",
            "owner": "unspecified",
            "owner_evidence": None,
            # 'Friday' is in the text, so this should pass and parse!
            "due_text": "by Friday",
            "due_date": "YYYY-MM-DD", # Let the system overwrite this
            "evidence": "to {{ORG_1}} by Friday"
        })

        # Test valid parsing (Friday after 2026-03-10)
        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        act = result["actions"][0]
        assert act["due_raw"] == "by Friday"
        assert act["due_date"] == "2026-03-13" # Friday after Tuesday March 10th

        # Test fabricated due_text
        raw["actions"][0]["due_text"] = "by Monday" # Hallucinated
        result2 = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        act2 = result2["actions"][0]
        assert act2["due_raw"] == "by Monday"
        assert act2["due_date"] is None

    def test_guardrail_5_unmapped_markers(self):
        """If an action contains a marker not in the map, it should be dropped."""
        raw = get_base_json()
        raw["actions"].append({
            "task": "Task for {{PERSON_99}}", # {{PERSON_99}} doesn't exist
            "owner": "unspecified",
            "owner_evidence": None,
            "due_text": "unspecified",
            "due_date": "unspecified",
            "evidence": "{{PERSON_2}} is sending the revised drawings"
        })
        
        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)
        assert len(result["actions"]) == 0

    def test_fatal_leak_prevention(self):
        """If Claude outputs the REAL name instead of the marker, it raises SecurityError."""
        raw = get_base_json()
        raw["actions"].append({
            "task": "Task",
            "owner": "Mike", # Leaked original value!
            "owner_evidence": None,
            "due_text": "unspecified",
            "due_date": "unspecified",
            "evidence": "{{PERSON_2}} is sending the revised drawings"
        })

        with pytest.raises(SecurityError):
            apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)

    @pytest.mark.parametrize(
        ("owner", "owner_evidence", "expected_reason"),
        [
            ("{{PERSON_2}}", None, "evidence nula"),
            ("{{PERSON_2}}", "The drawings are due Friday.", "evidence sin el nombre"),
            ("Reviewer", "Reviewer sends the revised drawings.", "owner not in roster"),
        ],
    )
    def test_owner_discard_diagnostic_is_indexed_and_sanitized(
        self, capsys, owner, owner_evidence, expected_reason
    ):
        raw = get_base_json()
        raw["actions"].append(
            {
                "task": "Send the revised drawings",
                "owner": owner,
                "owner_evidence": owner_evidence,
                "due_text": "unspecified",
                "due_date": "unspecified",
                "evidence": "{{PERSON_2}} is sending the revised drawings",
            }
        )

        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)

        assert result["actions"][0]["owner"] == "unspecified"
        diagnostic = capsys.readouterr().out
        assert "[DIAGNOSTIC] Owner discarded for action 0:" in diagnostic
        assert expected_reason in diagnostic
        assert "{{PERSON_2}}" not in diagnostic
        assert "revised drawings" not in diagnostic

    def test_owner_evidence_in_spanish_must_contain_the_placeholder(self, capsys):
        masked_text = "{{PERSON_1}} enviará el informe mañana."
        raw = get_base_json()
        raw["actions"].append(
            {
                "task": "Enviar el informe",
                "owner": "{{PERSON_1}}",
                "owner_evidence": "Yo me encargo del informe.",
                "due_text": "mañana",
                "due_date": "unspecified",
                "evidence": masked_text,
            }
        )

        result = apply_guardrails(
            raw, masked_text, {"{{PERSON_1}}": "Persona sintética"}, MEETING_DATE
        )

        assert result["actions"][0]["owner"] == "unspecified"
        assert "evidence sin el nombre" in capsys.readouterr().out

    def test_owner_evidence_marker_with_case_or_spacing_variation_currently_fails(
        self, capsys
    ):
        raw = get_base_json()
        raw["actions"].append(
            {
                "task": "Send the revised drawings",
                "owner": "{{PERSON_2}}",
                "owner_evidence": "{{ person_2 }} is sending the revised drawings",
                "due_text": "unspecified",
                "due_date": "unspecified",
                "evidence": "{{PERSON_2}} is sending the revised drawings",
            }
        )

        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)

        assert result["actions"][0]["owner"] == "unspecified"
        diagnostic = capsys.readouterr().out
        assert "evidence sin el nombre" in diagnostic
        assert "owner_in_sanitized_notes=True" in diagnostic
        assert "evidence_literal_substring=False" in diagnostic
        assert "owner_in_roster=True" in diagnostic
        assert "owner_format=marker" in diagnostic
        assert "evidence_marker_formats=marker" in diagnostic
        assert "owner_evidence_equals_action_evidence=False" in diagnostic

    def test_diagnostic_marks_identical_owner_and_action_evidence(self, capsys):
        raw = get_base_json()
        evidence = "{{PERSON_2}} is sending the revised drawings"
        raw["actions"].append(
            {
                "task": "Send the revised drawings",
                "owner": "Reviewer",
                "owner_evidence": evidence,
                "due_text": "unspecified",
                "due_date": "unspecified",
                "evidence": evidence,
            }
        )

        result = apply_guardrails(raw, MASKED_TEXT, TOKEN_MAP, MEETING_DATE)

        assert result["actions"][0]["owner"] == "unspecified"
        assert "owner_evidence_equals_action_evidence=True" in capsys.readouterr().out
