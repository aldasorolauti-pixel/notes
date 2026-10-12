"""
P4 Phase 1 — Sanitization (mask-then-rehydrate).

Masks sensitive entities (people, orgs, emails, phones, etc.) in meeting notes
while preserving dates and deadlines so Claude can extract them.

Usage:
    from p4.sanitize import Sanitizer
    s = Sanitizer("data/entities.json", "data/nicknames.json")
    masked, token_map = s.mask(text)

    # Or run directly:
    python -m p4.sanitize
"""

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import NlpEngineProvider

# ---------- Configuration ----------

MODEL = "en_core_web_sm"   # Switch to "en_core_web_lg" for production
SPANISH_MODEL = "es_core_news_sm"

# Entities to detect. DATE_TIME is intentionally EXCLUDED so that
# dates and deadlines remain visible in the masked text for Claude.
DETECT_ENTITIES = [
    "PERSON", "ORG",
    "EMAIL_ADDRESS", "PHONE_NUMBER",
    "US_SSN", "US_BANK_NUMBER", "CREDIT_CARD",
    "PROJECT_ID",
]


class TokenMap(dict[str, str]):
    """Marker map with local casing metadata for lossless rehydration."""

    def __init__(self, *args, case_variants: dict[str, list[str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_variants = case_variants or {}

MARKER_RE = re.compile(r"\{\{[A-Z_]+_\d+\}\}")

COMMON_WORDS = {
    "a", "al", "and", "are", "bien", "but", "by", "con", "como", "dale",
    "de", "del", "el", "ella", "en", "exacto", "for", "gracias", "hola",
    "i", "la", "las", "lo", "los", "mal", "me", "mi", "no", "of", "ok",
    "or", "para", "perfecto", "please", "por", "que", "sí", "si", "the",
    "this", "to", "un", "una", "we", "yes", "you", "yo",
    "answer", "participant", "question", "speaker", "respuesta", "pregunta",
    "dejá", "deja", "listo", "quién", "quien", "qué", "que", "cómo", "como",
    "estamos", "están", "estan", "somos", "presentes", "and", "hello",
    "eh", "mmm", "ah", "che", "uf", "prefiero", "quedemos", "pasemos",
    "seguimos", "necesitás", "necesitas",
}

_SPACY_STOPWORDS: dict[str, set[str]] = {}
for _lang in ("es", "en"):
    try:
        from spacy.lang import es as _es_lang
        from spacy.lang import en as _en_lang
        _SPACY_STOPWORDS[_lang] = set(
            (_es_lang.STOP_WORDS if _lang == "es" else _en_lang.STOP_WORDS)
        )
    except Exception:
        _SPACY_STOPWORDS[_lang] = set()

COMMON_WORDS.update(word.casefold() for words in _SPACY_STOPWORDS.values() for word in words)

_ATTENDEE_PREFIX = re.compile(
    r"\b(?:estamos|están|estan|somos|presentes|we\s+are|we're|present)\s*:\s*",
    re.IGNORECASE,
)
_ATTENDEE_LINE = re.compile(
    r"\b(?:estamos|están|estan|somos|presentes|we\s+are|we're|present)\b"
    r"\s*:?\s*(?P<names>[^\n.;!?]+)",
    re.IGNORECASE,
)
_NAME_TOKEN = r"[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúñü�'-]*"


def _fold(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    ).replace("�", "")


def _looks_like_person(value: str, score: float = 1.0) -> bool:
    words = value.split()
    return (
        len(words) <= 3
        and score >= 0.75
        and all(word[:1].isupper() for word in words)
        and all(_fold(word) not in COMMON_WORDS for word in words)
    )


def _is_common_word(value: str) -> bool:
    return _fold(value).strip(".,;:!?¿¡") in COMMON_WORDS


def _is_fallback_function_word(value: str) -> bool:
    folded = _fold(value).strip(".,;:!?¿¡")
    if folded in COMMON_WORDS:
        return True
    return bool(re.search(
        r"(?:emos|amos|imos|iste|isteis|ando|iendo|aré|eré|iré|ás|és|ís)$",
        folded,
    ))


def _split_attendees(value: str) -> list[str]:
    value = re.sub(r"\s+(?:y|and)\s+(?:yo|I|me)\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:y|and)\s+(?=[A-ZÁÉÍÓÚÜÑ])", ",", value)
    parts = [part.strip(" \t,") for part in value.split(",")]
    result = []
    for part in parts:
        part = re.sub(
            r"^(?:yo|me|myself|and|y|los|las|the|participantes?)\b\s*",
            "",
            part,
            flags=re.IGNORECASE,
        ).strip()
        if part and _looks_like_person(part):
            result.append(part)
    return result


def _roster_details(
    text: str,
    participants: list[str],
    analyzer: AnalyzerEngine | None = None,
) -> tuple[list[str], dict[str, set[str]]]:
    candidates: list[str] = []
    origins: dict[str, set[str]] = {}

    def add(value: str, origin: str) -> None:
        value = value.strip(" \t,.;:!?¿¡()")
        if (
            not _looks_like_person(value)
            or any(_is_common_word(word) or _is_fallback_function_word(word) for word in value.split())
        ):
            return
        if analyzer is not None and origin in {"vocative", "attendees", "NER"}:
            language = _language_for_paragraph(text, analyzer)
            start = text.casefold().find(value.casefold())
            has_language_model = language in getattr(analyzer.nlp_engine, "nlp", {})
            if (
                has_language_model
                and not _has_spanish_signal(text)
                and start >= 0
                and not _has_name_pos(text, start, start + len(value), language, analyzer)
            ):
                return
            if (
                has_language_model
                and start >= 0
                and _is_common_opener(text, start, start + len(value), language, analyzer)
            ):
                return
        if _looks_like_person(value):
            candidates.append(value)
            origins.setdefault(_fold(value), set()).add(origin)

    for value in participants:
        add(value, "participants")

    for match in _ATTENDEE_LINE.finditer(text):
        for value in _split_attendees(match.group("names")):
            add(value, "attendees")

    vocative_patterns = [
        rf"(?m)^(?P<name>{_NAME_TOKEN}(?:\s+{_NAME_TOKEN})?),",
        rf"(?m)^(?P<name>{_NAME_TOKEN})(?:\s+\([^)]*\))?\s*:",
        rf"(?i)(?:^|[¿?,.])\s*(?P<name>{_NAME_TOKEN})(?=\s*[,.?])",
        rf"(?i)\b(?:hola|gracias|hello|thanks)\s+(?P<name>{_NAME_TOKEN})\b",
    ]
    for pattern in vocative_patterns:
        for match in re.finditer(pattern, text):
            add(match.group("name"), "vocative")

    context_patterns = [
        rf"\b(?:con|with|dijo|said|habló con|spoke with|gracias a|thanks to)\s+"
        rf"(?P<name>{_NAME_TOKEN}(?:\s+{_NAME_TOKEN})?)",
    ]
    for pattern in context_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            add(match.group("name"), "context")

    return list(dict.fromkeys(candidates)), origins


# ---------- Data loading ----------

def load_entities(path: str | Path) -> dict:
    """Load the configured entity catalog."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_nicknames(path: str | Path) -> dict:
    """Load the configured nickname catalog."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------- Analyzer builder ----------

def _person_terms(entities: dict, nicknames: dict) -> list[str]:
    """Generate all name variants for deny-list matching."""
    terms = []
    for person in entities.get("people", []):
        full = person["full_name"]
        parts = full.split()
        first, last = parts[0], parts[-1]
        # Full name, first, last, explicit aliases, and nickname variants
        variants = {full, first, last}
        variants.update(person.get("aliases", []))
        variants.update(nicknames.get(first, []))
        terms.extend(variants)
    return list(set(terms))


def _org_terms(entities: dict) -> list[str]:
    """Generate all org name variants for deny-list matching."""
    terms = []
    for org in entities.get("orgs", []):
        terms.append(org["name"])
        terms.extend(org.get("aliases", []))
    return list(set(terms))


def build_analyzer(
    entities: dict,
    nicknames: dict,
    model: str = MODEL,
) -> AnalyzerEngine:
    """Build a Presidio AnalyzerEngine with custom deny-list recognizers."""
    models = [{"lang_code": "en", "model_name": model}]
    try:
        import spacy
        spacy.load(SPANISH_MODEL)
        models.append({"lang_code": "es", "model_name": SPANISH_MODEL})
    except Exception:
        pass
    provider = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": models,
    })
    analyzer = AnalyzerEngine(
        nlp_engine=provider.create_engine(),
        supported_languages=[model["lang_code"] for model in models],
    )
    analyzer._p4_entities = entities
    analyzer._p4_nicknames = nicknames

    # Deny-list: people
    person_words = _person_terms(entities, nicknames)
    if person_words:
        analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="PERSON",
                deny_list=person_words,
                name="deny_PERSON",
            )
        )

    # Deny-list: organizations
    org_words = _org_terms(entities)
    if org_words:
        analyzer.registry.add_recognizer(
            PatternRecognizer(
                supported_entity="ORG",
                deny_list=org_words,
                name="deny_ORG",
            )
        )

    # Regex for internal project identifiers.
    analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="PROJECT_ID",
            patterns=[Pattern("proj_id", r"\b\d{4}-\d{3}\b", 0.6)],
            name="regex_PROJECT_ID",
        )
    )

    return analyzer


# ---------- Core masking ----------

def _language_for_paragraph(paragraph: str, analyzer: AnalyzerEngine) -> str:
    spanish_words = len(re.findall(r"\b(el|la|los|las|que|para|una|con|por|yo)\b", paragraph.casefold()))
    english_words = len(re.findall(r"\b(the|and|that|for|with|one|i|you)\b", paragraph.casefold()))
    language = "es" if spanish_words > english_words else "en"
    return language if language in analyzer.supported_languages else "en"


def _has_spanish_signal(text: str) -> bool:
    return bool(re.search(r"[áéíóúñ¿¡]", text.casefold())) or len(re.findall(
        r"\b(el|la|los|las|que|para|una|con|por|yo|estamos|cómo|como)\b",
        text.casefold(),
    )) > 1


def _roster_candidates(text: str, participants: list[str]) -> list[str]:
    return _roster_details(text, participants)[0]


def _extend_roster_names(
    text: str,
    roster: list[str],
    roster_origins: dict[str, set[str]],
) -> None:
    """Add capitalized surname tokens that immediately follow roster names."""
    token_pattern = re.compile(
        r"(?P<separator>\s+)"
        r"(?P<token>[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúñü'-]*)"
    )
    for name in list(roster):
        if len(name.split()) != 1:
            continue
        name_pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE)
        for match in name_pattern.finditer(text):
            end = match.end()
            parts = [match.group()]
            for _ in range(2):
                following = token_pattern.match(text, end)
                if following is None or _is_common_word(following.group("token")):
                    break
                parts.append(following.group("token"))
                end = following.end()
            if len(parts) == 1:
                continue
            full_name = " ".join(parts)
            folded = _fold(full_name)
            if full_name not in roster:
                roster.append(full_name)
                roster_origins.setdefault(folded, set()).add("roster_extension")


def _merge_aliases(names: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    for name in names:
        folded = _fold(name)
        first = folded.split()[0]
        group = next(
            (item for item in groups
             if _fold(item[0]).split()[0][0:1] == first[0:1]
             and (
                 _fold(item[0]).split()[0].startswith(first)
                 or first.startswith(_fold(item[0]).split()[0])
             )),
            None,
        )
        if group is None:
            groups.append([name])
        elif name not in group:
            group.append(name)
    return groups


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - 24)
    right = min(len(text), end + 24)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _residue_report(masked_text: str, roster: list[str]) -> tuple[Counter[str], Counter[str]]:
    failures: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    for name in roster:
        if _is_common_word(name):
            continue
        count = len(re.findall(r"(?<!\w)" + re.escape(name) + r"(?!\w)", masked_text, re.IGNORECASE))
        if count:
            failures[name] += count
    for match in re.finditer(r"\b[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñü'-]*\b", masked_text):
        if masked_text.rfind("{{", 0, match.start()) > masked_text.rfind("}}", 0, match.start()):
            continue
        if match.start() == 0 or masked_text[match.start() - 1] in ".!?\n¿¡":
            continue
        if _is_common_word(match.group()):
            continue
        if _fold(match.group()) not in {_fold(name) for name in roster}:
            warnings[match.group()] += 1
    return failures, warnings


def _has_name_pos(
    paragraph: str,
    start: int,
    end: int,
    language: str,
    analyzer: AnalyzerEngine,
) -> bool:
    nlp = getattr(getattr(analyzer, "nlp_engine", None), "nlp", {}).get(language)
    if nlp is None:
        return True
    doc = nlp(paragraph)
    tokens = [token for token in doc if token.idx < end and token.idx + len(token) > start]
    return bool(tokens) and all(token.pos_ == "PROPN" for token in tokens)


def _is_common_opener(text: str, start: int, end: int, language: str, analyzer: AnalyzerEngine) -> bool:
    nlp = getattr(getattr(analyzer, "nlp_engine", None), "nlp", {}).get(language)
    if nlp is None:
        return False
    doc = nlp(text)
    token = next((item for item in doc if item.idx == start), None)
    if token is None:
        return False
    if token.pos_ in {"ADJ", "ADV", "INTJ", "VERB", "AUX", "PRON"}:
        return True
    if token.dep_ == "nsubj" and end < len(text) and text[end:].lstrip().startswith(","):
        return True
    if (
        token.dep_ == "npadvmod"
        and end < len(text)
        and text[end:].lstrip().startswith(",")
    ):
        following = next((item for item in doc if item.idx >= end and not item.is_punct), None)
        return following is not None and following.pos_ in {"PRON", "DET"}
    return False


def mask(
    text: str,
    analyzer: AnalyzerEngine,
    participants: list[str] | None = None,
    mask_orgs: bool = False,
    diagnostics: dict | None = None,
) -> tuple[str, dict[str, str]]:
    """
    Mask sensitive entities in text.

    Returns:
        (masked_text, token_map)
        token_map: {"{{PERSON_1}}": "a detected person", ...}
    """
    participants = participants or []
    roster, roster_origins = _roster_details(text, participants, analyzer)
    _extend_roster_names(text, roster, roster_origins)
    for catalog_name in _person_terms(
        getattr(analyzer, "_p4_entities", {}),
        getattr(analyzer, "_p4_nicknames", {}),
    ):
        if re.search(r"(?<!\w)" + re.escape(catalog_name) + r"(?!\w)", text, re.IGNORECASE):
            if not _is_common_word(catalog_name):
                roster.append(catalog_name)
                roster_origins.setdefault(_fold(catalog_name), set()).add("NER")
    roster = list(dict.fromkeys(roster))
    roster_folds = {_fold(name) for name in roster}
    for match in re.finditer(r"\b[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúñü�'-]*\b", text):
        value = match.group()
        folded = _fold(value)
        if (
            not _is_common_word(value)
            and any(
                folded.startswith(existing) or existing.startswith(folded)
                for existing in roster_folds
            )
        ):
            roster.append(value)
            roster_origins.setdefault(folded, set()).add("NER")
            roster_folds.add(folded)
    roster = list(dict.fromkeys(roster))
    results = []
    discarded: list[dict[str, str]] = []
    offset = 0
    for paragraph in re.split(r"\n\s*\n", text):
        language = _language_for_paragraph(paragraph, analyzer)
        for result in analyzer.analyze(text=paragraph, language=language, entities=DETECT_ENTITIES):
            value = paragraph[result.start:result.end]
            if result.entity_type == "PERSON":
                if not _looks_like_person(value, result.score):
                    discarded.append({"value": value, "reason": "common word, capitalization, token count, or low confidence"})
                    continue
                if (
                    _fold(value) not in roster_folds
                    and not (
                        language == "en"
                        and _has_spanish_signal(paragraph)
                    )
                    and not _has_name_pos(paragraph, result.start, result.end, language, analyzer)
                ):
                    discarded.append({"value": value, "reason": "grammatical tag is not PROPN"})
                    continue
                at_sentence_start = result.start == 0 or paragraph[result.start - 1] in ".!?\n¿¡"
                if at_sentence_start and _fold(value) not in roster_folds and len(value.split()) == 1:
                    discarded.append({"value": value, "reason": "sentence start without roster or name evidence"})
                    continue
                if _fold(value) not in roster_folds:
                    roster_origins.setdefault(_fold(value), set()).add("NER")
                    roster.append(value)
                    roster_folds.add(_fold(value))
            configured_orgs = {
                _fold(value)
                for value in _org_terms(getattr(analyzer, "_p4_entities", {}))
            }
            if (
                result.entity_type == "ORG"
                and not mask_orgs
                and _fold(value) not in configured_orgs
            ):
                continue
            result.start += offset
            result.end += offset
            results.append(result)
        offset += len(paragraph) + 2

    aliases = _merge_aliases(list(dict.fromkeys(roster)))
    alias_lookup = {}
    for group in aliases:
        canonical = min(group, key=lambda item: text.casefold().find(item.casefold()))
        for alias in group:
            alias_lookup[_fold(alias)] = canonical
    alias_forms: dict[str, list[str]] = {}
    for alias in roster:
        alias_forms.setdefault(_fold(alias), []).append(alias)
    for alias, canonical in alias_lookup.items():
        for form in alias_forms.get(alias, [alias]):
            pattern = re.compile(r"(?<!\w)" + re.escape(form) + r"(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(text):
                if _is_common_word(form) and match.group()[:1].islower():
                    continue
                results.append(type("Result", (), {
                    "start": match.start(), "end": match.end(),
                    "entity_type": "PERSON", "score": 1.0,
                })())

    # Resolve overlaps: sort by start, keep longest span at each position
    results.sort(key=lambda r: (r.start, -(r.end - r.start)))
    kept, last_end = [], -1
    for r in results:
        if r.start >= last_end:
            kept.append(r)
            last_end = r.end

    # Build masked text and token map
    mapping: dict[str, str] = {}   # canonical folded value -> marker
    originals: dict[str, str] = {}
    counters: dict[str, int] = {}
    out: list[str] = []
    pos = 0

    for r in kept:
        original = text[r.start:r.end]
        is_roster_value = _fold(original) in alias_lookup
        canonical = alias_lookup.get(_fold(original), original)
        key = _fold(canonical) if is_roster_value else canonical
        if key not in mapping:
            counters[r.entity_type] = counters.get(r.entity_type, 0) + 1
            mapping[key] = f"{{{{{r.entity_type}_{counters[r.entity_type]}}}}}"
            originals[key] = canonical
        out.append(text[pos:r.start])
        out.append(mapping[key])
        pos = r.end

    out.append(text[pos:])
    masked_text = "".join(out)

    # Reverse the map: marker -> original (this is what rehydrate needs)
    case_variants: dict[str, list[str]] = {}
    for r in kept:
        value = text[r.start:r.end]
        canonical = alias_lookup.get(_fold(value), value)
        marker = mapping[_fold(canonical) if _fold(value) in alias_lookup else canonical]
        case_variants.setdefault(marker, []).append(value)
    token_map = TokenMap(
        {marker: originals[key] for key, marker in mapping.items()},
        case_variants=case_variants,
    )
    token_map.masked_text = masked_text
    token_map.occurrence_variants = case_variants
    failures, warnings = _residue_report(masked_text, roster)
    if diagnostics is not None:
        diagnostics.update({
            "roster": {name: sorted(roster_origins.get(_fold(name), {"catalog"})) for name in roster},
            "aliases": aliases,
            "replacements": {
                token_map[marker]: len(re.findall(re.escape(marker), masked_text))
                for marker in token_map
            },
            "discarded": discarded,
            "residue_failures": dict(failures),
            "residue_warnings": dict(warnings),
        })
    if failures:
        details = ", ".join(f"{name} ({count})" for name, count in failures.items())
        raise RuntimeError(f"Sanitizer residue failure: {details}")

    return masked_text, token_map


# ---------- Convenience: Sanitizer class ----------

class Sanitizer:
    """All-in-one sanitizer that loads config and exposes mask()."""

    def __init__(
        self,
        entities_path: str | Path = "data/entities.json",
        nicknames_path: str | Path = "data/nicknames.json",
        model: str = MODEL,
        participants: list[str] | None = None,
        aliases_path: str | Path | None = None,
    ):
        self.entities = load_entities(entities_path)
        self.nicknames = load_nicknames(nicknames_path)
        if aliases_path and Path(aliases_path).exists():
            manual_aliases = load_nicknames(aliases_path)
            for canonical, aliases in manual_aliases.items():
                self.nicknames.setdefault(canonical, []).extend(aliases)
        self.analyzer = build_analyzer(self.entities, self.nicknames, model)
        self.participants = list(participants or [])
        self.last_diagnostics: dict = {}

    def mask(
        self,
        text: str,
        participants: list[str] | None = None,
        mask_orgs: bool = False,
    ) -> tuple[str, dict[str, str]]:
        roster = self.participants + (participants or [])
        self.last_diagnostics = {}
        return mask(text, self.analyzer, roster, mask_orgs, self.last_diagnostics)


# ---------- CLI demo ----------

if __name__ == "__main__":
    import argparse
    import sys

    base = Path(__file__).resolve().parent.parent

    parser = argparse.ArgumentParser(description="Mask meeting text without calling any API.")
    parser.add_argument("file", help="UTF-8 text file to mask")
    parser.add_argument("--dry-run", action="store_true", help="Print masked text and local statistics")
    parser.add_argument("--participants", default="", help="Comma-separated participant names")
    parser.add_argument("--aliases", default=None, help="Optional JSON alias mapping")
    parser.add_argument("--mask-orgs", action="store_true", help="Mask detected companies and products")
    args = parser.parse_args()
    s = Sanitizer(
        entities_path=base / "data" / "entities.json",
        nicknames_path=base / "data" / "nicknames.json",
        aliases_path=args.aliases,
    )
    text = Path(args.file).read_text(encoding="utf-8")
    participants = [item.strip() for item in args.participants.split(",") if item.strip()]

    s.participants.extend(participants)
    masked, rmap = s.mask(text, mask_orgs=args.mask_orgs)

    print("=" * 60)
    print("MASKED:\n", masked)
    print("\nSTATISTICS:")
    counts = {}
    for marker in rmap:
        kind = marker.split("_", 1)[0].strip("{")
        counts[kind] = counts.get(kind, 0) + 1
    print("markers_by_type:", counts)
    print("roster:", s.last_diagnostics.get("roster", {}))
    print("aliases:", s.last_diagnostics.get("aliases", []))
    print("replacements:", s.last_diagnostics.get("replacements", {}))
    print("discarded:", s.last_diagnostics.get("discarded", []))
    print("residue_failures:", s.last_diagnostics.get("residue_failures", {}))
    print("unmasked_entities_warning:", s.last_diagnostics.get("residue_warnings", {}))
    if not args.dry_run:
        print("\nRun with --dry-run to suppress any non-statistical demo output.")
