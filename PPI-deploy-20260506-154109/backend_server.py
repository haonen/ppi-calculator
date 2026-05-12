from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from config import load_feishu_settings
from feishu_client import FeishuClient
from ppi_processor import process_records


BACKEND_VERSION = "ppi-backend-2026-05-06-rsp-estimated-review-v4"


HOST = os.getenv("PPI_BACKEND_HOST", "127.0.0.1")
PORT = int(os.getenv("PPI_BACKEND_PORT", "8000"))
TRIGGER_TOKEN = os.getenv("PPI_TRIGGER_TOKEN", "dev-token-change-me")
STATUS_FIELD = os.getenv("PPI_STATUS_FIELD", "PPI Status")
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-PPI-Trigger-Token")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


REQUIRED_INPUT_FIELDS = {"Brand", "Campaign", "Link"}


def get_ppi_table_id(client: FeishuClient, app_token: str, table_name: str) -> str:
    for table in client.list_tables(app_token):
        if table.get("name") == table_name:
            return table["table_id"]
    raise RuntimeError(f"Table not found: {table_name}")


def existing_field_name(client: FeishuClient, app_token: str, table_id: str, field_name: str) -> str | None:
    fields = client.list_fields(app_token, table_id)
    for field in fields:
        if field.get("field_name") == field_name:
            return field_name
    return None


def validate_ppi_table_fields(client: FeishuClient, app_token: str, table_id: str, link_field: str) -> None:
    field_names = {field.get("field_name") for field in client.list_fields(app_token, table_id)}
    required = set(REQUIRED_INPUT_FIELDS)
    required.discard("Link")
    required.add(link_field)
    missing = sorted(field for field in required if field not in field_names)
    if missing:
        raise RuntimeError(
            "Current table is missing required fields: "
            + ", ".join(missing)
            + ". Required fields: Brand, Campaign, Link."
        )


def records_with_links(client: FeishuClient, app_token: str, table_id: str, link_field: str) -> list[str]:
    records = client.list_records(app_token, table_id)
    return [
        record["record_id"]
        for record in records
        if record.get("fields", {}).get(link_field)
    ]


def set_job(job_id: str, **values: Any) -> None:
    with JOBS_LOCK:
        JOBS.setdefault(job_id, {}).update(values)


def run_ppi_job(job_id: str, table_id: str, record_ids: list[str]) -> None:
    set_job(job_id, status="running", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        result = process_records(record_ids, ppi_table_id=table_id)
        set_job(
            job_id,
            status="done",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            result=result,
        )
        print(f"[backend] job {job_id} done: {result}")
    except Exception as exc:
        set_job(
            job_id,
            status="error",
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=str(exc),
        )
        print(f"[backend] job {job_id} failed: {exc}")


def submit_ppi_job(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_feishu_settings()
    client = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)
    requested_table_id = payload.get("table_id")
    ppi_table_id = requested_table_id or get_ppi_table_id(
        client,
        settings.feishu_app_token,
        settings.ppi_table_name,
    )
    validate_ppi_table_fields(client, settings.feishu_app_token, ppi_table_id, settings.ppi_link_field)

    mode = payload.get("mode")
    record_ids = payload.get("record_ids") or []
    if mode == "current_view":
        record_ids = records_with_links(
            client,
            settings.feishu_app_token,
            ppi_table_id,
            settings.ppi_link_field,
        )

    if not record_ids:
        raise RuntimeError("No records to process.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_field = existing_field_name(client, settings.feishu_app_token, ppi_table_id, STATUS_FIELD)
    if status_field:
        client.batch_update_records(
            settings.feishu_app_token,
            ppi_table_id,
            [
                {
                    "record_id": record_id,
                    "fields": {
                        status_field: f"Running at {now}",
                    },
                }
                for record_id in record_ids
            ],
        )
    job_id = uuid.uuid4().hex[:12]
    set_job(
        job_id,
        status="queued",
        mode=mode,
        submitted=len(record_ids),
        table_id=ppi_table_id,
        created_at=now,
    )
    thread = threading.Thread(target=run_ppi_job, args=(job_id, ppi_table_id, record_ids), daemon=True)
    thread.start()

    return {
        "ok": True,
        "job_id": job_id,
        "mode": mode,
        "submitted": len(record_ids),
        "table_id": ppi_table_id,
        "status": "queued",
    }


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, 200, {"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            json_response(self, 200, {"ok": True, "version": BACKEND_VERSION})
            return
        if path == "/version":
            json_response(self, 200, {"ok": True, "version": BACKEND_VERSION})
            return
        if path.startswith("/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id, {}))
            if not job:
                json_response(self, 404, {"ok": False, "error": "Job not found"})
                return
            json_response(self, 200, {"ok": True, "job_id": job_id, **job})
            return
        json_response(self, 404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        try:
            if urlparse(self.path).path != "/run-ppi":
                json_response(self, 404, {"ok": False, "error": "Not found"})
                return

            if self.headers.get("X-PPI-Trigger-Token") != TRIGGER_TOKEN:
                json_response(self, 401, {"ok": False, "error": "Invalid trigger token"})
                return

            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            result = submit_ppi_job(payload)
            json_response(self, 200, result)
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[backend] {self.address_string()} - {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"PPI backend listening on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
