# P4 — Privacy-first meeting notes extraction

P4 turns unstructured meeting notes or transcripts into a concise, evidence-backed
record of:

- decisions;
- actions with an owner and a resolved deadline;
- risks;
- open questions.

It is designed for messy, multilingual notes (Spanish, English, or mixed) where
inventing a person or date is worse than reporting an explicit `unspecified`.

## Why this architecture

P4 follows a local **mask → cloud extraction → validate → rehydrate** flow:

```text
raw notes
   │
   ├─ local sanitization: typed placeholders for people, organizations,
   │  contact details, and other sensitive entities
   ▼
masked notes ──► LLM extraction
                    │
                    ├─ schema and evidence validation
                    ├─ deterministic date resolution in Python
                    └─ no invented owners, dates, or evidence
   ▼
validated masked JSON ──► local rehydration ──► JSON + Markdown report
```

This separation preserves semantic roles for the model without sending the
original sensitive values to the provider. Dates remain visible during
sanitization so relative expressions such as “tomorrow” can be resolved from
the meeting date. Owners, evidence, and open questions are checked in code
after the model responds.

The design is informed by:

- **MemPrivacy: Privacy-Preserving Personalized Memory Management for
  Edge-Cloud Agents** (Chen et al., 2026): type-aware placeholders and local
  restoration;
- **Enterprise-Scale PII De-Identification with Microsoft Presidio
  Anonymizer** (Atri, 2025): local entity analysis and configurable
  recognizers;
- **Action-Item-Driven Summarization of Long Meeting Transcripts**
  (Golia & Kalita, 2023): summaries organized around actionable outcomes
  rather than generic dialogue compression.

The source PDFs are intentionally not part of the repository. They are
background references, not application inputs or runtime dependencies.

## Features

- Local PII masking with Microsoft Presidio and spaCy.
- Masked extraction through the Anthropic Messages API.
- No `temperature` parameter: extraction is constrained by the prompt,
  schema, evidence checks, and deterministic post-processing.
- Bilingual and mixed-language date resolution.
- ISO dates (`YYYY-MM-DD`) and optional `due_time` only when a time was stated.
- Explicit `unspecified` owners and deadlines instead of guesses.
- Evidence validation for actions, owners, risks, and open questions.
- FastAPI endpoint plus a minimal browser interface.
- Deterministic noisy-variant and name-leak testing tools.

## Requirements

- Python 3.11 or newer.
- An Anthropic API key.
- spaCy language models used by the sanitizer.

## Installation

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m spacy download es_core_news_sm
```

Set the key in the environment or in a local `.env` file. Never commit it:

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
```

Or copy the included template and replace its placeholder:

```powershell
Copy-Item .env.example .env
notepad .env
```

## Run the web app

```powershell
uvicorn api.main:app --reload
```

Open <http://127.0.0.1:8000/>.

The browser interface accepts pasted notes or a `.txt` file. The meeting date
is required when processing a file and is sent as the reference date for
relative deadlines.

## API

### `GET /api/health`

Returns:

```json
{"status": "ok"}
```

### `POST /api/extract`

Request:

```json
{
  "notes": "Jordan will send the draft tomorrow.",
  "meeting_date": "2026-10-09",
  "language": "en"
}
```

`notes` is required and limited to 100 KB. `meeting_date` is an ISO date.
The API returns `400` for invalid input, `413` for oversized notes, and `502`
when extraction fails. The API never returns or logs the API key or note
contents.

Response fields:

```json
{
  "decisions": [],
  "actions": [],
  "risks": [],
  "open_questions": [],
  "markdown": "..."
}
```

Actions also expose `owner_unspecified` and `due_unspecified` flags for
clients that want to render missing information explicitly.

## Testing

Install the development dependencies from `requirements.txt`, then run:

```powershell
pytest
```

The API tests mock the LLM and do not make network calls. The full extraction
path requires `ANTHROPIC_API_KEY` only when running the application against
the real provider.

## Local privacy boundary

The sanitizer runs before the LLM call. The guardrails reject malformed or
unsupported model output, and rehydration happens locally. Do not add raw
meeting notes, API keys, `.env` files, virtual environments, or generated
reports to version control.

## Repository layout

```text
api/       FastAPI application
data/      local entity and nickname configuration
p4/        sanitizer, extractor, date resolver, rehydrator, renderer
tests/     unit and API tests
tools/     deterministic noise and leak-check utilities
web/       minimal frontend
```
