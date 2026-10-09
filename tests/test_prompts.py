from p4.prompts import SYSTEM_PROMPT_V1


def test_prompt_requires_owner_evidence_to_name_the_owner_in_both_languages():
    assert "owner_evidence" in SYSTEM_PROMPT_V1
    assert "CONTAINS the owner's name or placeholder" in SYSTEM_PROMPT_V1
    assert "yo me encargo" in SYSTEM_PROMPT_V1
    assert 'set owner to "unspecified"' in SYSTEM_PROMPT_V1


def test_prompt_keeps_one_action_for_one_task_with_follow_up_details():
    assert (
        "ONE TASK, ONE ACTION: If a sentence describes a single task with several parts"
        in SYSTEM_PROMPT_V1
    )
    assert "different owners or different deadlines" in SYSTEM_PROMPT_V1


def test_prompt_uses_summary_evidence_for_unnamed_commitments_and_conflicts():
    assert '"ok, lo mando el lunes"' in SYSTEM_PROMPT_V1
    assert '"Marta manda el borrador el lunes"' in SYSTEM_PROMPT_V1
    assert "Marta's person placeholder as owner" in SYSTEM_PROMPT_V1
    assert '("A or B")' in SYSTEM_PROMPT_V1
    assert 'set owner to "unspecified"' in SYSTEM_PROMPT_V1
    assert "If the speaker has no name in the notes" in SYSTEM_PROMPT_V1


def test_prompt_separates_open_questions_from_actions():
    assert (
        'OPEN QUESTION OR ACTION, NOT BOTH: If a task appears as an open question'
        in SYSTEM_PROMPT_V1
    )
    assert '("no sé quién lo hace" or equivalent)' in SYSTEM_PROMPT_V1
    assert (
        'UNRESOLVED TOPICS: A topic explicitly marked as "queda abierto"'
        in SYSTEM_PROMPT_V1
    )
    assert "belongs in Open Questions, not Actions" in SYSTEM_PROMPT_V1


def test_schema_describes_owner_evidence_as_named_sentence():
    from p4.prompts import OUTPUT_SCHEMA

    description = OUTPUT_SCHEMA["properties"]["actions"]["items"]["properties"][
        "owner_evidence"
    ]["description"]
    assert "Quote the sentence that contains the owner's name or marker." in description
    assert "closing recap" in description
    assert "set owner to unspecified and this field to null" in description


def test_prompt_forbids_invented_times():
    assert "NO INVENTED TIMES:" in SYSTEM_PROMPT_V1
    assert '"a primera hora"' in SYSTEM_PROMPT_V1
    assert '"mañana por la mañana"' in SYSTEM_PROMPT_V1
    assert "without an explicit clock time" in SYSTEM_PROMPT_V1
    assert "Include due_time only when an hour is explicitly stated" in SYSTEM_PROMPT_V1


def test_prompt_splits_only_when_owner_or_deadline_differs():
    assert "SPLIT ONLY BY DEADLINE OR OWNER:" in SYSTEM_PROMPT_V1
    assert '"escribo hoy, llamo mañana"' in SYSTEM_PROMPT_V1
    assert "same deadline and owner stay in one action" in SYSTEM_PROMPT_V1


def test_prompt_distinguishes_actions_from_decisions():
    assert "ACTION VS DECISION:" in SYSTEM_PROMPT_V1
    assert "do not repeat it as an action unless it has its own owner and deadline" in SYSTEM_PROMPT_V1


def test_prompt_requires_contiguous_evidence_quotes():
    assert "EVIDENCE MUST BE ONE CONTIGUOUS QUOTE:" in SYSTEM_PROMPT_V1
    assert "one continuous fragment of the notes" in SYSTEM_PROMPT_V1
    assert "never multiple sentences joined together" in SYSTEM_PROMPT_V1
