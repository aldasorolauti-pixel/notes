"""
P4 Final Pipeline

Orchestrates Phase 1 (Sanitization), Phase 3 (Extraction & Validation), 
and Phase 4 (Rehydrate & Render).
"""

from pathlib import Path
from p4.sanitize import Sanitizer
from p4.extract import call_llm, apply_guardrails
from p4.rehydrate import rehydrate
from p4.render import render_markdown

def run_pipeline(
    notes_text: str,
    meeting_date: str,
    mock_llm_response: dict = None,
    participants: list[str] | None = None,
) -> str:
    """
    End-to-End processing of unstructured meeting notes.

    Args:
        notes_text: Unstructured meeting notes text.
        meeting_date: YYYY-MM-DD meeting date for relative deadlines calculation.
        mock_llm_response: Used for testing without API Key.
    """
    base_dir = Path(__file__).resolve().parent.parent

    # PHASE 1: Sanitize
    print("[*] Sanitizing notes...")
    sanitizer = Sanitizer(
        entities_path=base_dir / "data" / "entities.json",
        nicknames_path=base_dir / "data" / "nicknames.json",
        participants=participants,
    )
    masked_text, token_map = sanitizer.mask(notes_text)

    # PHASE 3: Extraction and Validation
    print("[*] Extracting JSON structure (Call LLM + Guardrails)...")
    if mock_llm_response:
        raw_json = mock_llm_response
    else:
        # In a real environment, this connects to Anthropic.
        raw_json = call_llm(masked_text, meeting_date)

    validated_json = apply_guardrails(raw_json, masked_text, token_map, meeting_date)

    # PHASE 4: Rehydration & Render
    print("[*] Rehydrating markers back to sensitive information...")
    rehydrated_data = rehydrate(validated_json, token_map)
    
    print("[*] Rendering Markdown PM view...")
    final_markdown = render_markdown(rehydrated_data)
    
    # Optionally, we can safely delete 'token_map' here from memory if strict security needs demand it.
    del token_map 
    
    return final_markdown
