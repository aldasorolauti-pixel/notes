import pytest

from p4.extract import apply_guardrails, resolve_due_date


@pytest.mark.parametrize(
    ("raw", "base", "expected_date", "expected_time"),
    [
        ("today", "2026-01-05", "2026-01-05", None),
        ("\u006d\u0061\u00f1\u0061\u006e\u0061", "2026-02-28", "2026-03-01", None),
        ("pasado \u006d\u0061\u00f1\u0061\u006e\u0061", "2026-12-30", "2027-01-01", None),
        ("a primera hora", "2026-03-11", "2026-03-11", "09:00"),
        ("end of day", "2026-03-11", "2026-03-11", "17:00"),
        ("antes de las 5 pm", "2026-03-11", "2026-03-11", "17:00"),
        ("next monday", "2026-03-11", "2026-03-16", None),
        ("la semana que viene", "2026-12-28", None, None),
        ("fin de mes", "2026-12-11", "2026-12-31", None),
        ("in 3 days", "2026-01-30", "2026-02-02", None),
        ("en 5 horas", "2026-12-31", "2026-12-31", "05:00"),
        ("in a bit", "2026-04-02", "2026-04-02", None),
        ("right after this", "2026-04-02", "2026-04-02", None),
        ("en un rato", "2026-04-02", "2026-04-02", None),
        ("by end of day Monday", "2026-04-02", "2026-04-06", "17:00"),
        ("para el cierre del viernes", "2026-04-02", "2026-04-03", "17:00"),
        ("Thursday at noon", "2026-04-03", "2026-04-09", "12:00"),
        ("tmrw", "2026-04-02", "2026-04-03", None),
        ("\u006d\u0061\u00f1\u0061\u006e\u0061 a la \u006d\u0061\u00f1\u0061\u006e\u0061", "2026-04-02", "2026-04-03", "09:00"),
        ("by March 20", "2026-03-21", "2027-03-20", None),
        ("el lunes a la tarde", "2026-04-02", "2026-04-06", None),
        ("Monday afternoon", "2026-04-02", "2026-04-06", None),
        ("antes del 30 de octubre", "2026-10-08", "2026-10-30", None),
        ("el 15 de marzo", "2026-03-01", "2026-03-15", None),
        ("para el 3 de noviembre", "2026-10-08", "2026-11-03", None),
        ("today before five", "2026-04-02", "2026-04-02", "17:00"),
        ("antes de las cinco", "2026-04-02", "2026-04-02", "17:00"),
    ],
)
def test_resolve_due_date_is_bilingual_and_calendar_based(raw, base, expected_date, expected_time):
    assert resolve_due_date(raw, base) == (expected_date, expected_time)


@pytest.mark.parametrize("raw", ["soon", "pronto", "miércoles"])
def test_ambiguous_or_same_weekday_stays_unresolved(raw):
    assert resolve_due_date(raw, "2026-03-11") == (None, None)


def test_weekday_matching_meeting_day_stays_unresolved():
    assert resolve_due_date("by Thursday", "2026-04-02") == (None, None)


def test_evidence_matching_normalizes_case_and_whitespace():
    masked = "The team will send the report\nbefore noon."
    raw = {
        "meeting": {"title": "Review", "date": "2026-03-11"},
        "decisions": [],
        "actions": [
            {
                "task": "Send report",
                "owner": "unspecified",
                "owner_evidence": None,
                "due_raw": "before noon",
                "evidence": "THE TEAM WILL SEND THE REPORT before noon.",
            }
        ],
        "open_questions": [
            {"text": "Which format?", "evidence": " no question here "},
        ],
        "risks": [],
    }
    result = apply_guardrails(raw, masked, {}, "2026-03-11")
    assert len(result["actions"]) == 1
    assert result["actions"][0]["due_date"] is None
    assert len(result["open_questions"]) == 0


def test_later_answer_removes_open_question_and_keeps_unanswered_question():
    masked = (
        "Which format should we use? We will decide after review. "
        "Who owns the handoff? That remains undefined. "
        "The format is PDF, so the first question is answered."
    )
    raw = {
        "meeting": {"title": "Review", "date": "2026-04-02"},
        "decisions": [],
        "actions": [],
        "open_questions": [
            {
                "text": "Which format should we use?",
                "evidence": "Which format should we use?",
                "resolution_check": "answered later",
            },
            {
                "text": "Who owns the handoff?",
                "evidence": "Who owns the handoff? That remains undefined.",
                "resolution_check": "no later answer found",
            },
        ],
        "risks": [],
    }
    result = apply_guardrails(raw, masked, {}, "2026-04-02")
    assert [item["text"] for item in result["open_questions"]] == ["Who owns the handoff?"]
