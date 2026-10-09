from p4.render import render_markdown


def test_render_uses_spanish_labels_for_all_sections_and_owner_note():
    output = render_markdown(
        {
            "meeting": {"title": "Reunión", "date": "2026-10-08"},
            "decisions": [],
            "actions": [
                {
                    "task": "Enviar informe",
                    "owner": "unspecified",
                    "owner_note": "reclamada por dos personas",
                    "due_date": None,
                    "due_raw": "pronto",
                    "due_note": "pronto",
                    "evidence": "Enviar informe",
                }
            ],
            "risks": [{"text": "La demora", "evidence": "hay riesgo de demora"}],
            "open_questions": [{"text": "¿Quién lo hará?", "evidence": "¿Quién lo hará?"}],
        }
    )

    assert "Responsable: sin especificar (reclamada por dos personas)" in output
    assert "Fecha límite: pronto" in output
    assert "Evidencia: hay riesgo de demora" in output
    assert "Evidence:" not in output


def test_render_uses_english_labels_and_due_time():
    output = render_markdown(
        {
            "meeting": {"title": "Planning", "date": "2026-10-08"},
            "decisions": [],
            "actions": [
                {
                    "task": "Send report",
                    "owner": "{{PERSON_1}}",
                    "owner_note": None,
                    "due_date": "2026-10-09",
                    "due_time": "09:00",
                    "evidence": "Send report tomorrow",
                }
            ],
            "risks": [{"text": "Delay", "evidence": "the schedule is at risk"}],
            "open_questions": [{"text": "Who approves?", "evidence": "Who approves?"}],
        }
    )

    assert "Owner: {{PERSON_1}}" in output
    assert "Due: 2026-10-09 at 09:00" in output
    assert "Evidence: the schedule is at risk" in output
    assert "Responsable:" not in output
