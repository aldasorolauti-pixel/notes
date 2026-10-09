import os
import json
import re
import calendar
from datetime import date, datetime, timedelta
from typing import List, Optional, Any, Tuple
from pydantic import BaseModel, Field, ValidationError

# Initialize Anthropic SDK lazily
try:
    from anthropic import Anthropic
    _api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=_api_key) if _api_key else None
except Exception:
    client = None

# ---------- Pydantic Models for Validation ----------

class MeetingInfo(BaseModel):
    title: str
    date: str

class DecisionItem(BaseModel):
    text: str
    evidence: str

class ActionItem(BaseModel):
    task: str
    owner: str
    owner_note: Optional[str] = None
    owner_evidence: Optional[str]
    due_raw: Optional[str] = None
    due_text: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    due_note: Optional[str] = None
    evidence: str

class OpenQuestionItem(BaseModel):
    text: str
    evidence: str
    resolution_check: str = ""

class RiskItem(BaseModel):
    text: str
    evidence: str

class ExtractionResult(BaseModel):
    meeting: MeetingInfo
    decisions: List[DecisionItem]
    actions: List[ActionItem]
    open_questions: List[OpenQuestionItem]
    risks: List[RiskItem] = Field(default_factory=list)

# ---------- Deterministic Guardrails ----------

def _evidence_in_text(evidence: str, text: str) -> bool:
    """Check evidence after normalizing case and runs of whitespace."""
    clean_ev = evidence.strip().strip("\"'")
    normalize = lambda value: re.sub(r"\s+", " ", value).casefold().strip()
    return normalize(clean_ev) in normalize(text)


def _parse_meeting_date(meeting_date: str) -> date:
    try:
        return datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("meeting_date must be an ISO date (YYYY-MM-DD)") from exc


def _time_value(hour: str, minute: str = "00", meridiem: str = "") -> Optional[str]:
    value = int(hour)
    if meridiem:
        meridiem = meridiem.casefold()
        if value < 1 or value > 12:
            return None
        if meridiem == "pm" and value != 12:
            value += 12
        if meridiem == "am" and value == 12:
            value = 0
    if value > 23 or int(minute) > 59:
        return None
    return f"{value:02d}:{int(minute):02d}"


def _clean_owner(owner: str) -> str:
    """Normalize formatting and reject non-identifying role labels."""
    cleaned = re.sub(r"^\s*(?:->|→)\s*", "", owner).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned.casefold() in {
        "participant", "patient", "team", "speaker", "person", "member",
        "grupo", "participante", "paciente", "equipo", "unspecified",
    }:
        return "unspecified"
    return cleaned


def _owner_is_valid_marker(owner: str, token_map: dict) -> bool:
    return bool(re.fullmatch(r"\{\{PERSON_\d+\}\}", owner)) and owner in token_map


def _owner_format(value: str) -> str:
    if re.fullmatch(r"(?:\{\{\s*[A-Za-z]+_\d+\s*\}\}|\[[A-Za-z]+_\d+\])", value.strip()):
        return "marker"
    if re.fullmatch(r"[A-Za-zÀ-ÿ]+(?:[\s-]+[A-Za-zÀ-ÿ]+)*", value.strip()):
        return "real-name"
    return "other"


def _marker_formats(value: str) -> list[str]:
    markers = re.findall(r"\{\{[^{}]+\}\}", value)
    if not markers:
        return ["none"]
    return sorted({_owner_format(marker) for marker in markers})


def _log_owner_discard(
    action_index: int,
    reason: str,
    *,
    owner_in_notes: bool,
    evidence_in_notes: bool,
    owner_in_roster: bool,
    owner_evidence_equals_action_evidence: bool,
    owner_format: str,
    evidence_formats: list[str],
    evidence_length: int,
) -> None:
    print(
        "[DIAGNOSTIC] Owner discarded for action "
        f"{action_index}: {reason}; owner_in_sanitized_notes={owner_in_notes}; "
        f"evidence_literal_substring={evidence_in_notes}; "
        f"owner_in_roster={owner_in_roster}; owner_format={owner_format}; "
        "owner_evidence_equals_action_evidence="
        f"{owner_evidence_equals_action_evidence}; "
        f"evidence_marker_formats={','.join(evidence_formats)}; "
        f"evidence_length={evidence_length}"
    )


def _action_key(action: ActionItem) -> tuple[str, str]:
    task = re.sub(r"\W+", " ", action.task.casefold()).strip()
    owner = re.sub(r"\W+", " ", action.owner.casefold()).strip()
    return task, owner


def resolve_due_date(due_raw: Optional[str], meeting_date: str) -> Tuple[Optional[str], Optional[str]]:
    """Resolve supported bilingual relative-date patterns without model date arithmetic."""
    if not due_raw or due_raw.casefold().strip() in {"unspecified", "none", "null"}:
        return None, None
    base = _parse_meeting_date(meeting_date)
    raw = re.sub(r"\s+", " ", due_raw.casefold().strip())
    ascii_raw = raw.translate(str.maketrans({
        "\u00e1": "a", "\u00e9": "e", "\u00ed": "i", "\u00f3": "o",
        "\u00fa": "u", "\u00f1": "n",
    }))
    weekdays = {
        "monday": 0, "lunes": 0, "martes": 1, "tuesday": 1, "miércoles": 2, "miercoles": 2,
        "wednesday": 2, "jueves": 3, "thursday": 3, "viernes": 4, "friday": 4,
        "sábado": 5, "sabado": 5, "saturday": 5, "domingo": 6, "sunday": 6,
    }
    word_hours = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "once": 11, "doce": 12, "twelve": 12, "cinco": 5,
    }

    immediate_before = re.search(
        r"\b(?:today|hoy)\s+(?:before|antes de las?)\s+"
        r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|once|doce|cinco|twelve)"
        r"(?::(\d{2}))?\s*(am|pm)?\b",
        raw,
    )
    if immediate_before:
        hour = str(word_hours.get(immediate_before.group(1), immediate_before.group(1)))
        resolved = _time_value(
            hour, immediate_before.group(2) or "00", immediate_before.group(3) or ""
        )
        if not immediate_before.group(3) and hour == "5":
            resolved = "17:00"
        return base.isoformat(), resolved
    if re.search(r"\b(today|hoy)\b", raw):
        return base.isoformat(), None
    if re.search(r"\b(pasado manana|day after tomorrow)\b", ascii_raw):
        return (base + timedelta(days=2)).isoformat(), None
    if re.search(r"\b(tomorrow morning|manana a la manana)\b", ascii_raw):
        return (base + timedelta(days=1)).isoformat(), "09:00"
    if re.search(r"\b(tmrw|tmr|tom|tomorrow|manana)\b", ascii_raw):
        return (base + timedelta(days=1)).isoformat(), None
    if re.search(r"\b(in a bit|in a moment|right after this|ahorita|en un rato|ya mismo)\b", raw):
        return base.isoformat(), None
    if re.search(r"\b(tonight|esta noche)\b", raw):
        return base.isoformat(), "20:00"
    if re.search(r"\b(tomorrow|mañana)\b", raw):
        return (base + timedelta(days=1)).isoformat(), None
    weekday_period = re.search(
        r"\b(?:on\s+|el\s+)?(monday|lunes|martes|tuesday|miércoles|miercoles|wednesday|"
        r"jueves|thursday|viernes|friday|sábado|sabado|saturday|domingo|sunday)"
        r"\s+(?:(?:in\s+the|a\s+la)\s+)?(morning|afternoon|evening|night|mañana|manana|tarde|noche)\b",
        raw,
    )
    if weekday_period:
        weekday = weekdays[weekday_period.group(1)]
        delta = (weekday - base.weekday()) % 7
        if delta == 0:
            return None, None
        period = weekday_period.group(2)
        return (base + timedelta(days=delta)).isoformat(), None
    if re.search(r"\b(this afternoon|esta tarde|tarde|afternoon)\b", raw):
        return base.isoformat(), None
    if re.search(r"\b(first thing|a primera hora)\b", raw):
        return base.isoformat(), "09:00"
    weekday_period = re.search(
        r"\b(?:on\s+|el\s+)?(monday|lunes|martes|tuesday|miércoles|miercoles|wednesday|"
        r"jueves|thursday|viernes|friday|sábado|sabado|saturday|domingo|sunday)"
        r"\s+(?:(?:in\s+the|a\s+la)\s+)?(morning|afternoon|evening|night|mañana|manana|tarde|noche)\b",
        raw,
    )
    if weekday_period:
        weekday = weekdays[weekday_period.group(1)]
        delta = (weekday - base.weekday()) % 7
        if delta == 0:
            return None, None
        period = weekday_period.group(2)
        return (base + timedelta(days=delta)).isoformat(), None
    end_of_day = re.search(
        r"\b(?:end of day|eod|cob|al final del día|al final del dia|cierre)\b"
        r"(?:\s+(?:(?:on|el|del|de)\s+)?(?P<weekday>[a-záéíóúñ]+))?",
        raw,
    )
    if end_of_day:
        weekday_name = end_of_day.group("weekday")
        if weekday_name:
            weekday = next(
                (day for name, day in weekdays.items() if name == weekday_name), None
            )
            if weekday is not None:
                delta = (weekday - base.weekday()) % 7
                if delta == 0:
                    return None, None
                return (base + timedelta(days=delta)).isoformat(), "17:00"
        return base.isoformat(), "17:00"

    simple_noon = re.search(
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+noon\b",
        raw,
    )
    if simple_noon:
        weekday = weekdays[simple_noon.group(1)]
        delta = (weekday - base.weekday()) % 7
        return ((base + timedelta(days=delta)).isoformat(), "12:00") if delta else (None, None)

    weekday_at_noon = re.search(
        r"\b(?:on\s+)?(monday|martes|tuesday|miércoles|miercoles|wednesday|"
        r"jueves|thursday|viernes|friday|sábado|sabado|saturday|domingo|sunday)"
        r"\s+at\s+noon\b",
        raw,
    )
    if weekday_at_noon:
        weekday = weekdays[weekday_at_noon.group(1)]
        delta = (weekday - base.weekday()) % 7
        return ((base + timedelta(days=delta)).isoformat(), "12:00") if delta else (None, None)
    weekday_with_time = re.search(
        r"\b(?:on|el)?\s*(monday|martes|tuesday|miércoles|miercoles|wednesday|"
        r"jueves|thursday|viernes|friday|sábado|sabado|saturday|domingo|sunday)"
        r"(?:\s+at\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?"
        r"|\s+a\s+(?P<es_hour>\d{1,2})(?::(?P<es_minute>\d{2}))?\s*(?P<es_ampm>am|pm)?)?",
        raw,
    )
    if weekday_with_time:
        weekday_name = weekday_with_time.group(1)
        weekday = weekdays[weekday_name]
        delta = (weekday - base.weekday()) % 7
        if delta == 0:
            return None, None
        hour = weekday_with_time.group("hour") or weekday_with_time.group("es_hour")
        if hour:
            minute = weekday_with_time.group("minute") or weekday_with_time.group("es_minute") or "00"
            ampm = weekday_with_time.group("ampm") or weekday_with_time.group("es_ampm") or ""
            time = "12:00" if ampm == "noon" else _time_value(hour, minute, ampm)
        else:
            time = None
        return (base + timedelta(days=delta)).isoformat(), time

    before_time = re.search(
        r"\b(?:before|antes de las?)\s+(\d{1,2}|one|two|three|four|five|six|"
        r"seven|eight|nine|ten|once|doce|cinco|twelve)(?::(\d{2}))?\s*(am|pm)?\b", raw
    )
    if before_time:
        hour = before_time.group(1)
        hour = str(word_hours.get(hour, hour))
        resolved = _time_value(
            hour, before_time.group(2) or "00", before_time.group(3) or ""
        )
        if not before_time.group(3) and hour == "5":
            resolved = "17:00"
        return (base.isoformat(), resolved) if resolved else (None, None)

    weekday = next((day for name, day in weekdays.items() if re.search(rf"\b{name}\b", raw)), None)
    if weekday is not None:
        delta = (weekday - base.weekday()) % 7
        return ((base + timedelta(days=delta)).isoformat(), None) if delta else (None, None)

    if re.search(r"\b(next week|la semana que viene|la próxima semana|la proxima semana)\b", raw):
        return None, None
    if re.search(r"\b(end of month|fin de mes)\b", raw):
        return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1]).isoformat(), None

    relative = re.search(r"\b(?:in|en)\s+(\d+)\s+(day|days|día|días|dias|hour|hours|hora|horas)\b", raw)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit in {"hour", "hours", "hora", "horas"}:
            target = datetime.combine(base, datetime.min.time()) + timedelta(hours=amount)
            return target.date().isoformat(), target.strftime("%H:%M")
        return (base + timedelta(days=amount)).isoformat(), None

    month_day = re.search(
        r"\b(?:by|para el|para|on)?\s*"
        r"(january|enero|february|febrero|march|marzo|april|abril|may|mayo|"
        r"june|junio|july|julio|august|agosto|september|septiembre|setiembre|"
        r"october|octubre|november|noviembre|december|diciembre)\s+(\d{1,2})\b",
        raw,
    )
    if not month_day:
        month_day = re.search(
            r"\b(?:before|antes del|el|para el|para)?\s*(\d{1,2})\s+"
            r"(?:de\s+)?"
            r"(january|enero|february|febrero|march|marzo|april|abril|may|mayo|"
            r"june|junio|july|julio|august|agosto|september|septiembre|setiembre|"
            r"october|octubre|november|noviembre|december|diciembre)\b",
            raw,
        )
    if month_day:
        months = {
            "january": 1, "enero": 1, "february": 2, "febrero": 2,
            "march": 3, "marzo": 3, "april": 4, "abril": 4, "may": 5, "mayo": 5,
            "june": 6, "junio": 6, "july": 7, "julio": 7, "august": 8, "agosto": 8,
            "september": 9, "septiembre": 9, "setiembre": 9, "october": 10,
            "octubre": 10, "november": 11, "noviembre": 11, "december": 12, "diciembre": 12,
        }
        if month_day.group(1).isdigit():
            day = int(month_day.group(1))
            month = months[month_day.group(2)]
        else:
            month = months[month_day.group(1)]
            day = int(month_day.group(2))
        year = base.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None, None
        if candidate <= base:
            candidate = date(year + 1, month, day)
        return candidate.isoformat(), None

    return None, None


def _question_was_resolved(question: OpenQuestionItem, text: str) -> bool:
    """Reject questions whose later transcript contains an explicit resolution."""
    normalized = re.sub(r"\s+", " ", text).casefold()
    evidence = re.sub(r"\s+", " ", question.evidence.strip()).casefold()
    start = normalized.find(evidence)
    if start < 0:
        return False
    following = normalized[start + len(evidence):]
    question_terms = {
        term for term in re.findall(r"[a-záéíóúñ]{4,}", question.text.casefold())
        if term not in {"which", "what", "where", "when", "who", "cómo", "como", "qué", "que"}
    }
    resolution_markers = (
        "answered", "resolved", "confirmed", "we decided", "the answer is",
        "it will be", "yes,", "ya está", "se resolvió", "se decidió",
        "queda definido", "ya definimos", "está confirmado",
    )
    return any(
        marker in following and any(term in following for term in question_terms)
        for marker in resolution_markers
    )

def apply_guardrails(raw_json: dict, masked_text: str, token_map: dict, meeting_date: str) -> dict:
    """
    Applies the 5 deterministic guardrails to the JSON output.
    Modifies and returns the cleaned dictionary.
    """
    # 1. Validate schema via Pydantic
    try:
        parsed = ExtractionResult(**raw_json)
    except ValidationError as e:
        raise ValueError(f"Schema validation failed: {e}")

    # Guardrail 5 setup: Extract all placeholders present in the output
    valid_markers = set(token_map.keys())

    def check_markers(s: str) -> bool:
        """Returns False if the string contains a placeholder that wasn't in the token map."""
        if not s: return True
        found = set(re.findall(r"\{\{[A-Z_]+_\d+\}\}", s))
        return found.issubset(valid_markers)

    # Pre-check: Ensure no actual leak occurred before processing markers
    # Using a recursive function to find exact fields and avoid substring false alerts
    def check_leaks_in_dict(data: Any, path: str = ""):
        if isinstance(data, dict):
            for k, v in data.items():
                check_leaks_in_dict(v, f"{path}.{k}" if path else k)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                check_leaks_in_dict(item, f"{path}[{i}]")
        elif isinstance(data, str):
            for marker, original_val in token_map.items():
                category = marker.strip("{}").split("_")[0] # e.g. PERSON, ORG
                
                # Require a word boundary match to avoid substring false positives unconditionally
                pattern = r'\b' + re.escape(original_val) + r'\b'
                matches = list(re.finditer(pattern, data, flags=re.IGNORECASE))
                
                is_leak = False
                for match in matches:
                    start = match.start()
                    prefix = data[max(0, start-4):start]
                    is_leak = True
                    break
                    
                if is_leak:
                    print("\n[DIAGNOSTICO B - FUGA DE VALOR ORIGINAL]")
                    print(f"1. Valor original correspondiente a {marker}: '{original_val}'")
                    print(f"2. Texto enmascarado enviado a la API:\n{masked_text}\n")
                    print(f"3. Valor en la key '{path}' devuelto por el modelo: '{data}'")

                    raise SecurityError(
                        f"FATAL: Unmasked value leak detected! \n"
                        f"- Category: {category} (Marker: {marker})\n"
                        f"- Found in JSON field: '{path}'\n"
                        f"The LLM hallucinated the original raw value instead of using the placeholder."
                    )

    check_leaks_in_dict(raw_json)

    cleaned_actions = []
    for action_index, act in enumerate(parsed.actions):
        # Check markers for task/evidence
        if not check_markers(act.task) or not check_markers(act.evidence):
            continue # Discard if it uses hallucinated markers

        # Guardrail 1: General evidence must exist
        if not _evidence_in_text(act.evidence, masked_text):
            continue # Drop the entire action if evidence is completely fabricated

        # Guardrail 2: Owner verification
        act.owner = _clean_owner(act.owner)
        if act.owner == "unspecified":
            act.owner_note = None
        elif act.owner_note and len(act.owner_note.split()) > 10:
            act.owner_note = None
        if act.owner != "unspecified":
            ev = act.owner_evidence or ""
            owner_in_notes = _evidence_in_text(act.owner, masked_text)
            evidence_in_notes = bool(ev.strip()) and ev.strip() in masked_text
            owner_in_roster = _owner_is_valid_marker(act.owner, token_map)
            owner_evidence_equals_action_evidence = (
                bool(ev.strip())
                and re.sub(r"\s+", " ", ev).casefold().strip()
                == re.sub(r"\s+", " ", act.evidence).casefold().strip()
            )
            owner_format = _owner_format(act.owner)
            evidence_formats = _marker_formats(ev)
            evidence_length = len(ev)

            def discard_owner(reason: str) -> None:
                _log_owner_discard(
                    action_index,
                    reason,
                    owner_in_notes=owner_in_notes,
                    evidence_in_notes=evidence_in_notes,
                    owner_in_roster=owner_in_roster,
                    owner_evidence_equals_action_evidence=(
                        owner_evidence_equals_action_evidence
                    ),
                    owner_format=owner_format,
                    evidence_formats=evidence_formats,
                    evidence_length=evidence_length,
                )

            if not _owner_is_valid_marker(act.owner, token_map):
                discard_owner("owner not in roster")
                act.owner = "unspecified"
                act.owner_evidence = None
            elif not ev.strip():
                discard_owner("evidence nula")
                act.owner = "unspecified"
                act.owner_evidence = None
            elif act.owner not in ev:
                discard_owner("evidence sin el nombre")
                act.owner = "unspecified"
                act.owner_evidence = None
            elif not _evidence_in_text(ev, masked_text):
                discard_owner("evidence no encontrada")
                act.owner = "unspecified"
                act.owner_evidence = None

        # Guardrails 3 & 4: deterministic bilingual relative-date resolution.
        due_raw = act.due_raw or act.due_text
        act.due_raw = due_raw
        act.due_text = None
        if due_raw and due_raw != "unspecified":
            if not _evidence_in_text(due_raw, masked_text):
                act.due_date = None
                act.due_time = None
                act.due_note = due_raw
            else:
                act.due_date, act.due_time = resolve_due_date(due_raw, meeting_date)
                act.due_note = None if act.due_date else due_raw
        else:
            act.due_date = None
            act.due_time = None
            act.due_note = None

        cleaned_actions.append(act)

    unique_actions = {}
    for action in cleaned_actions:
        key = _action_key(action)
        previous = unique_actions.get(key)
        action_score = (
            bool(action.due_date),
            bool(action.due_time),
            len(action.evidence),
        )
        previous_score = (
            bool(previous.due_date),
            bool(previous.due_time),
            len(previous.evidence),
        ) if previous else None
        if previous is None or action_score > previous_score:
            unique_actions[key] = action
    parsed.actions = list(unique_actions.values())
    
    # Also validate risks
    parsed.risks = [
        r for r in parsed.risks 
        if _evidence_in_text(r.evidence, masked_text) and check_markers(r.text)
    ]

    # Apply simplistic evidence guardrail to decisions and open questions
    parsed.decisions = [
        d for d in parsed.decisions 
        if _evidence_in_text(d.evidence, masked_text) and check_markers(d.text)
    ]
    
    parsed.open_questions = [
        q for q in parsed.open_questions 
        if _evidence_in_text(q.evidence, masked_text)
        and check_markers(q.text)
        and not _question_was_resolved(q, masked_text)
        and not any(
            marker in q.resolution_check.casefold()
            for marker in ("answered", "resolved", "respondida", "resuelta", "sí", "yes")
        )
    ]

    return parsed.model_dump()


class SecurityError(Exception):
    pass


# ---------- API Call Logic ----------

def call_llm(masked_text: str, meeting_date: str) -> dict:
    """
    Submits the prompt to Claude Haiku via Anthropic API.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    if not client:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set. Cannot call LLM.")
    
    from p4.prompts import SYSTEM_PROMPT_V1, build_user_message
    
    user_msg = build_user_message(masked_text, meeting_date)

    # Try calling with thinking explicitly disabled, fallback if SDK throws error due to beta mismatch.
    try:
        response = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=8192,
            system=SYSTEM_PROMPT_V1,
            thinking={"type": "disabled"},
            messages=[
                {"role": "user", "content": user_msg}
            ]
        )
    except Exception as e:
        if "thinking" in str(e).lower() or "unexpected keyword argument" in str(e).lower():
            response = client.messages.create(
                model="claude-haiku-5-5",
                max_tokens=8192,
                system=SYSTEM_PROMPT_V1,
                messages=[
                    {"role": "user", "content": user_msg}
                ]
            )
        else:
            raise e

    # Check for max_tokens limit reached prematurely
    if getattr(response, "stop_reason", None) == "max_tokens":
        usage = getattr(response, "usage", None)
        out_toks = getattr(usage, "output_tokens", "unknown") if usage else "unknown"
        
        # [DIAGNOSTICO A - MAX TOKENS]
        print("\n[DIAGNOSTICO A - MAX TOKENS]")
        block_types = [block.type for block in response.content]
        print(f"1. Tipos de bloque en response.content: {block_types}")
        print(f"2. response.usage: {getattr(usage, '__dict__', usage)}")
        print(f"3. Tamaño texto enviado: {len(user_msg)} caracteres")
        
        text_parts = [block.text for block in response.content if getattr(block, "type", "text") == "text"]
        full_text = "\n".join(text_parts)
        print(f"4. Output generado ({len(full_text)} caracteres totales):")
        print(f"--- PRIMEROS 500 CHARS ---\n{full_text[:500]}")
        print(f"--- ÚLTIMOS 500 CHARS ---\n{full_text[-500:]}\n")

        raise ValueError(f"LLM Error: stop_reason was 'max_tokens'. The model ran out of space to finish the output (used {out_toks} tokens). Try increasing max_tokens. (See debug above)")

    # Collect only TextBlocks — skip ThinkingBlock and other block types
    text_parts = [block.text for block in response.content if block.type == "text"]
    
    if not text_parts:
        block_types = [block.type for block in response.content]
        stop_reason = getattr(response, "stop_reason", "unknown")
        print(f"[ERROR DEBUG] stop_reason: {stop_reason}")
        print(f"[ERROR DEBUG] block types received: {block_types}")
        raise ValueError("No text block found in LLM response. The model may have returned only a ThinkingBlock.")
        
    response_text = "\n".join(text_parts)

    # Safely extract JSON in case LLM added markdown format ticks
    match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if match:
        response_text = match.group(0)

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON from LLM: {e}")
