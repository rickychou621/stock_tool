from contextlib import nullcontext
from threading import Event

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.screening import router
from app.screening.jobs import ScanJobManager
from app.screening.scan_service import ScanSummary, ScreeningScanService


@pytest.fixture
def manager(monkeypatch):
    manager = ScanJobManager(session_factory=lambda: nullcontext(None))
    monkeypatch.setattr(router, "manager", manager)
    monkeypatch.setattr("app.main.screening_manager", manager)
    yield manager
    manager.close()


def test_latest_without_scan_is_null(manager):
    with TestClient(app) as client:
        response = client.get("/screening/run/latest")
        assert response.status_code == 200
        assert response.json() is None


def test_running_job_returns_progress_and_rejects_second_start(manager, monkeypatch):
    entered, release = Event(), Event()

    def scan(self, progress):
        progress(1, 2)
        entered.set()
        assert release.wait(5)
        progress(2, 2)
        return ScanSummary(1, 2, 0, 0)

    monkeypatch.setattr(ScreeningScanService, "run_scan", scan)
    with TestClient(app) as client:
        try:
            response = client.post("/screening/run")
            assert response.status_code == 202
            assert entered.wait(5)
            job_id = response.json()["jobId"]
            assert client.get("/screening/run/latest").json() == {
                "jobId": job_id, "status": "running", "done": 1, "total": 2,
                "summary": None, "error": None,
            }
            busy = client.post("/screening/run")
            assert busy.status_code == 409
            assert busy.json()["detail"] == "已有掃描進行中，請等待完成。"
        finally:
            release.set()
        manager.close()
        done = client.get("/screening/run/latest").json()
        assert done["status"] == "done"
        assert done["done"] == done["total"] == 2
        assert done["summary"]["stocksScanned"] == 2
        assert done["error"] is None
        assert client.post("/screening/run").json()["jobId"] != job_id


def test_failed_job_exposes_exception_and_can_restart(manager, monkeypatch):
    def scan(self, progress):
        progress(1, 2)
        raise ValueError("失敗" * 150)

    monkeypatch.setattr(ScreeningScanService, "run_scan", scan)
    with TestClient(app) as client:
        response = client.post("/screening/run")
        manager.close()
        failed = client.get("/screening/run/latest").json()
        assert failed["jobId"] == response.json()["jobId"]
        assert failed["status"] == "failed"
        assert failed["summary"] is None
        assert failed["error"] == "ValueError: " + "失敗" * 100
        assert failed["done"] == 1
        assert client.post("/screening/run").status_code == 202
