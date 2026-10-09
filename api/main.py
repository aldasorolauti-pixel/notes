from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from p4.extract import apply_guardrails, call_llm
from p4.rehydrate import rehydrate
from p4.render import render_markdown
from p4.sanitize import Sanitizer

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
MAX_NOTES_BYTES = 100 * 1024


class ExtractRequest(BaseModel):
    notes: str
    meeting_date: str | None = None
    language: str | None = None

    @field_validator("notes")
    @classmethod
    def notes_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("notes must not be empty")
        if len(value.encode("utf-8")) > MAX_NOTES_BYTES:
            raise ValueError("notes exceeds the 100 KB limit")
        return value

    @field_validator("meeting_date")
    @classmethod
    def meeting_date_must_be_iso(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value


class ExtractResponse(BaseModel):
    decisions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    markdown: str


def _serialize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _run_extraction(payload: ExtractRequest) -> ExtractResponse:
    meeting_date = payload.meeting_date or date.today().isoformat()
    sanitizer = Sanitizer(
        entities_path=ROOT / "data" / "entities.json",
        nicknames_path=ROOT / "data" / "nicknames.json",
    )
    masked_text, token_map = sanitizer.mask(payload.notes)
    try:
        raw_json = call_llm(masked_text, meeting_date)
        validated = apply_guardrails(raw_json, masked_text, token_map, meeting_date)
        data = rehydrate(validated, token_map)
        markdown = render_markdown(data)
    finally:
        del token_map

    actions = []
    for action in data.get("actions", []):
        item = dict(action)
        item["owner_unspecified"] = item.get("owner") == "unspecified"
        item["due_unspecified"] = not item.get("due_date")
        actions.append(item)
    return ExtractResponse(
        decisions=data.get("decisions", []),
        actions=actions,
        risks=data.get("risks", []),
        open_questions=data.get("open_questions", []),
        markdown=markdown,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    yield


app = FastAPI(title="P4 Meeting Extraction API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    message = "Invalid request"
    status_code = 400
    for error in exc.errors():
        if error.get("type") == "value_error":
            message = str(error.get("msg", message))
        if "100 KB" in message:
            status_code = 413
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": "payload_too_large" if status_code == 413 else "invalid_input", "message": message}},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract", response_model=ExtractResponse)
async def extract(payload: ExtractRequest) -> ExtractResponse:
    try:
        return await asyncio.to_thread(_run_extraction, payload)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_error", "message": "Extraction service failed"},
        ) from exc


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
