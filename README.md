# P4 — Privacy-first meeting notes extraction

P4 turns unstructured meeting notes into evidence-backed action items, decisions,
risks, and open questions while masking selected sensitive entities locally.

> Early-stage project, tested on a small set of synthetic meetings.

## Example

`examples/meeting_es.txt` contains a short synthetic Spanish meeting with invented
names and no real data:

```text
Reunion breve: Bruno Salas coordina con Lara Mendez. Email: bruno.salas@example.com. Telefono: +54 11 5555 0199. Empresa: Lumen Ficticia. Producto: Faro Azul.
```

Run the local sanitizer without calling an API:

```powershell
python -m p4.sanitize --dry-run examples/meeting_es.txt
```

The verified masked text is:

```text
Reunion breve: {{PERSON_1}} coordina con {{PERSON_2}}. Email: {{EMAIL_ADDRESS_1}}. Telefono: {{PHONE_NUMBER_1}}. Empresa: Lumen Ficticia. Producto: {{PERSON_3}}.
```

The dry-run also shows local statistics and the reversible mapping; no model
provider is contacted.

## Architecture

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

Dates remain visible during sanitization so relative expressions such as
“tomorrow” can be resolved from the meeting date. Owners, evidence, and open
questions are checked in code after the model responds.

## Features

- Local entity masking with Microsoft Presidio and spaCy.
- Masked extraction through the Anthropic Messages API.
- Bilingual and mixed-language date resolution.
- ISO dates (`YYYY-MM-DD`) and optional `due_time` only when a time was stated.
- Explicit `unspecified` owners and deadlines instead of guesses.
- Evidence validation for actions, owners, risks, and open questions.
- FastAPI endpoint plus a minimal browser interface.
- Deterministic noisy-variant and name-leak testing tools.

## Limitations

- Masking covers people, emails and phone numbers. Company names, products, clients, amounts and other business data are NOT masked by default and are sent to the model provider as written.
- Detection relies on Presidio and spaCy models (`en_core_web_sm`, `es_core_news_sm`). Some names can be missed and some common words can be masked by mistake. The Presidio literature lists dependence on recognizer and NER model quality as a known limitation.
- Masked text is pseudonymized, not anonymized: a local mapping can restore the original values. This project does not claim GDPR, HIPAA or any other regulatory compliance.
- Always inspect the masked text with `python -m p4.sanitize --dry-run <file>` before sending confidential meetings to any provider.
- Owners and deadlines are left as "unspecified" when the notes do not state them. In transcripts without speaker labels, many owners will stay unspecified.
- Model output varies between runs. It was evaluated manually on a small set of synthetic meetings, not on a benchmark.

## Privacy notice

The provider receives the masked meeting text, the meeting date, and entities
that are not masked by the sanitizer. The original values and the local mapping
from placeholders to original values remain local. Rehydration also happens
locally after validation.

## Requirements and installation

- Python 3.11 or newer.
- An Anthropic API key for extraction (not needed for the sanitizer dry-run).
- spaCy models used by the sanitizer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m spacy download es_core_news_sm
```

Set `ANTHROPIC_API_KEY` in the environment or a local `.env` file. Never commit
the key.

## Run

```powershell
uvicorn api.main:app --reload
```

Open <http://127.0.0.1:8000/>.

The API accepts notes and a meeting date, and returns decisions, actions, risks,
open questions, and a Markdown report. The full extraction path requires the API
key; tests mock the LLM and do not make network calls.

## Testing

```powershell
pytest
```

## References and inspiration

P4 takes ideas from these references but does not reimplement or use the models
from the papers:

- Chen, Y., Zhao, J., Tang, B., Wang, H., Zhang, Y., Huang, F., Xiong, F., Li, Z. (2026). MemPrivacy: Privacy-Preserving Personalized Memory Management for Edge-Cloud Agents. arXiv:2605.09530. → Idea taken: placeholders tipados y restauración local. P4 NO usa sus modelos extractores entrenados ni su taxonomía.
- Atri, S. (2025). Enterprise-Scale PII De-Identification with Microsoft Presidio Anonymizer: Architecture, Use Cases, and Best Practices. IJAIBDCMS, 6(4), 176–180. doi:10.63282/3050-9416.IJAIBDCMS-V6I4P120. → Idea tomada: detección y anonimización local antes de enviar a un LLM, seudonimización reversible con mapeo.
- Golia, L., Kalita, J. (2023). Action-Item-Driven Summarization of Long Meeting Transcripts. NLPIR 2023, ACM. doi:10.1145/3639233.3639253. → Motivación: organizar la minuta alrededor de acciones. P4 usa un LLM con prompt y NO su pipeline de BART.
- Microsoft Presidio, <https://github.com/microsoft/presidio>

The reference PDFs are not included in the repository.

## License

MIT. See [LICENSE](LICENSE).
