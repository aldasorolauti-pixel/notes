"""
P4 Phase 4 — Render Markdown

Takes the completely rehydrated structured dictionary and transforms it 
into a formatted Markdown output for the Project Manager.
"""

import re

def _is_spanish(structured_data: dict) -> bool:
    text = " ".join(
        str(value)
        for section in ("meeting", "decisions", "actions", "risks", "open_questions")
        for value in structured_data.get(section, [])
    ).casefold()
    spanish = sum(
        len(re.findall(rf"\b{word}\b", text))
        for word in ("el", "la", "que", "y", "para", "una", "pregunta", "riesgo")
    )
    english = sum(
        len(re.findall(rf"\b{word}\b", text))
        for word in ("the", "and", "which", "for", "a", "question", "risk")
    )
    return spanish > english

def render_markdown(structured_data: dict) -> str:
    """
    Renders decisions, actions, and open questions to formatted Markdown.
    Highlights missing data (unspecified) with alert symbols.
    """
    
    meeting = structured_data.get("meeting", {})
    title = meeting.get("title", "Unnamed Meeting")
    date = meeting.get("date", "Unknown Date")
    spanish = _is_spanish(structured_data)

    labels = {
        "decisions": "Decisiones" if spanish else "Decisions",
        "actions": "Acciones" if spanish else "Actions",
        "risks": "Riesgos" if spanish else "Risks",
        "questions": "Preguntas abiertas" if spanish else "Open Questions",
        "evidence": "Evidencia" if spanish else "Evidence",
        "owner": "Responsable" if spanish else "Owner",
        "due": "Fecha límite" if spanish else "Due",
        "unspecified": "sin especificar" if spanish else "unspecified",
    }
    md = [f"# {'Elementos de acción' if spanish else 'Meeting Action Items'}: {title} ({date})\n"]
    
    # Decisions
    md.append(f"## {labels['decisions']}\n")
    decisions = structured_data.get("decisions", [])
    if decisions:
        for dec in decisions:
            md.append(f"- {dec['text']}")
    else:
        md.append(f"- *{'No se registraron decisiones.' if spanish else 'No decisions recorded.'}*")
    
    md.append(f"\n## {labels['actions']}\n")
    actions = structured_data.get("actions", [])
    if actions:
        for act in actions:
            task = act.get('task', '')
            owner = act.get('owner', 'unspecified')
            owner_note = act.get('owner_note', None)
            due_date = act.get('due_date', 'unspecified')
            due_time = act.get('due_time', None)
            due_note = act.get('due_note', None)
            
            # Format display alerts for missing info
            if owner == "unspecified":
                if owner_note:
                    owner_display = (
                        f"⚠ {labels['owner']}: {labels['unspecified']} "
                        f"({owner_note})"
                    )
                else:
                    owner_display = f"⚠ {labels['owner']}: {labels['unspecified']}"
            else:
                owner_display = f"{labels['owner']}: {owner}"
            
            # Preserve the source phrase only when Python could not resolve it.
            if not due_date:
                due_text = act.get("due_raw") or "unspecified"
                if due_note:
                    due_display = f"⚠ {labels['due']}: {due_note}"
                elif due_text != "unspecified":
                    due_display = f"⚠ {labels['due']}: {due_text}" 
                else:
                    due_display = f"⚠ {labels['due']}: {labels['unspecified']}"
            else:
                due_display = f"{labels['due']}: {due_date}"
                if due_time:
                    due_display += f" {'a las' if spanish else 'at'} {due_time}"

            md.append(f"- {task} — {owner_display} — {due_display} — {labels['evidence']}: {act.get('evidence', '')}")
    else:
        md.append(f"- *{'No se registraron acciones.' if spanish else 'No actions recorded.'}*")
        
    md.append(f"\n## {labels['risks']}\n")
    risks = structured_data.get("risks", [])
    if risks:
        for r in risks:
            md.append(f"- {r['text']} ({labels['evidence']}: {r['evidence']})")
    else:
        md.append(f"- *{'No se identificaron riesgos.' if spanish else 'No risks identified.'}*")

    md.append(f"\n## {labels['questions']}\n")
    questions = structured_data.get("open_questions", [])
    if questions:
        for q in questions:
            md.append(f"- {q['text']} ({labels['evidence']}: {q['evidence']})")
    else:
        md.append(f"- *{'No se registraron preguntas abiertas.' if spanish else 'No open questions recorded.'}*")
        
    return "\n".join(md)
