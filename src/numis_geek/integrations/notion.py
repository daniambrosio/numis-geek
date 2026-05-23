"""Notion API client used by services/notion_sync.

Thin wrapper around the official Notion HTTP API
(https://developers.notion.com/reference). Authenticates with an Internal
Integration token (Authorization: Bearer …) stored in IntegrationCredential
(provider=NOTION, key_name=NOTION_TOKEN). DB IDs are also stored as separate
IntegrationCredential rows so the user can configure them via the sysadmin
UI without touching code.

Used by `services/notion_sync.py`. Does NOT do any model translation —
that's the orchestrator's job. This layer only knows about Notion's
property-payload shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TIMEOUT = 30.0


class NotionError(RuntimeError):
    pass


class NotionNotFound(NotionError):
    pass


@dataclass(frozen=True)
class NotionPage:
    id: str
    last_edited_time: str  # ISO 8601 from Notion
    properties: dict[str, Any]
    url: str


class NotionClient:
    def __init__(self, token: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._token = token
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{NOTION_BASE}{path}"
        try:
            r = httpx.request(
                method, url, headers=self._headers(), json=json, timeout=self._timeout
            )
        except httpx.HTTPError as e:
            raise NotionError(f"Notion {method} {path} failed: {e}") from e
        if r.status_code == 404:
            raise NotionNotFound(f"Notion {method} {path}: 404")
        if r.status_code >= 400:
            raise NotionError(
                f"Notion {method} {path} returned {r.status_code}: {r.text[:500]}"
            )
        return r.json()

    def retrieve_page(self, page_id: str) -> NotionPage:
        data = self._request("GET", f"/pages/{page_id}")
        return NotionPage(
            id=data["id"],
            last_edited_time=data["last_edited_time"],
            properties=data.get("properties", {}),
            url=data.get("url", ""),
        )

    def create_page(self, database_id: str, properties: dict[str, Any]) -> NotionPage:
        body = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        data = self._request("POST", "/pages", json=body)
        return NotionPage(
            id=data["id"],
            last_edited_time=data["last_edited_time"],
            properties=data.get("properties", {}),
            url=data.get("url", ""),
        )

    def update_page(self, page_id: str, properties: dict[str, Any]) -> NotionPage:
        data = self._request("PATCH", f"/pages/{page_id}", json={"properties": properties})
        return NotionPage(
            id=data["id"],
            last_edited_time=data["last_edited_time"],
            properties=data.get("properties", {}),
            url=data.get("url", ""),
        )

    def query_database(
        self,
        database_id: str,
        filter_: dict[str, Any] | None = None,
        page_size: int = 100,
    ) -> list[NotionPage]:
        """Single-page query — does NOT auto-paginate. Caller handles cursors
        if needed (we never expect more than 100 hits per lookup)."""
        body: dict[str, Any] = {"page_size": page_size}
        if filter_:
            body["filter"] = filter_
        data = self._request("POST", f"/databases/{database_id}/query", json=body)
        return [
            NotionPage(
                id=row["id"],
                last_edited_time=row["last_edited_time"],
                properties=row.get("properties", {}),
                url=row.get("url", ""),
            )
            for row in data.get("results", [])
        ]


# ── Property builders ────────────────────────────────────────────────────────
# Helpers to build Notion property payloads for create/update. Each returns
# a property-value object as expected by Notion API.

def prop_title(value: str) -> dict[str, Any]:
    return {"title": [{"type": "text", "text": {"content": value}}]}


def prop_rich_text(value: str | None) -> dict[str, Any]:
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"type": "text", "text": {"content": value}}]}


def prop_number(value: float | None) -> dict[str, Any]:
    return {"number": value}


def prop_date(iso_date: str | None) -> dict[str, Any]:
    if not iso_date:
        return {"date": None}
    return {"date": {"start": iso_date}}


def prop_select(name: str | None) -> dict[str, Any]:
    if not name:
        return {"select": None}
    return {"select": {"name": name}}


def prop_relation(page_ids: list[str]) -> dict[str, Any]:
    return {"relation": [{"id": pid} for pid in page_ids if pid]}


def prop_checkbox(value: bool) -> dict[str, Any]:
    return {"checkbox": bool(value)}
