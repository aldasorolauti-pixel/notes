import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from fastapi.testclient import TestClient

from api import main


def test_health():
    with TestClient(main.app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_with_mocked_llm(monkeypatch):
    monkeypatch.setattr(
        main,
        "call_llm",
        lambda masked, meeting_date: {
            "meeting": {"title": "Review", "date": meeting_date},
            "decisions": [],
            "actions": [],
            "open_questions": [],
            "risks": [],
        },
    )
    with TestClient(main.app) as client:
        response = client.post("/api/extract", json={"notes": "Review the plan."})
    assert response.status_code == 200
    assert response.json()["actions"] == []
    assert "markdown" in response.json()


def test_extract_rejects_empty_notes():
    with TestClient(main.app) as client:
        response = client.post("/api/extract", json={"notes": "  "})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_input"


def test_extract_rejects_oversized_notes():
    with TestClient(main.app) as client:
        response = client.post("/api/extract", json={"notes": "x" * (100 * 1024 + 1)})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "payload_too_large"


def test_extract_maps_llm_failure_to_502(monkeypatch):
    monkeypatch.setattr(main, "call_llm", lambda masked, meeting_date: (_ for _ in ()).throw(RuntimeError("failed")))
    with TestClient(main.app) as client:
        response = client.post("/api/extract", json={"notes": "Review the plan."})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_error"
