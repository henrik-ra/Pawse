"""Cosmos DB persistence for Pawse — Entra ID (managed identity) only.

No keys, no connection strings. Authentication is via ``DefaultAzureCredential``,
which in Azure picks up the user-assigned managed identity named by the
``AZURE_CLIENT_ID`` environment variable (set by the Bicep deployment).

The store is intentionally *best-effort*: if Cosmos isn't configured (e.g. when
running the API locally without Azure), the calls degrade to no-ops / empty
results so the rest of the service keeps working.
"""
from __future__ import annotations

import os
from typing import Any

_endpoint = os.environ.get("AZURE_COSMOS_ENDPOINT")
_database_name = os.environ.get("COSMOS_DATABASE", "pawse")
_container_name = os.environ.get("COSMOS_CONTAINER", "dailyScores")

_container = None


def _connect():
    """Lazily create the Cosmos container client (cached). None if unconfigured."""
    global _container
    if _container is not None or not _endpoint:
        return _container

    from azure.cosmos import CosmosClient
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential(
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID")
    )
    client = CosmosClient(url=_endpoint, credential=credential)
    _container = client.get_database_client(_database_name).get_container_client(
        _container_name
    )
    return _container


def is_enabled() -> bool:
    """True when a Cosmos endpoint is configured."""
    return bool(_endpoint)


def _doc_id(user_id: str, date: str) -> str:
    return f"{user_id}::{date}"


def upsert_day(user_id: str, date: str, scored: dict[str, Any]) -> None:
    """Persist (or replace) the scored day for a user. Best-effort."""
    container = _connect()
    if container is None:
        return

    document = {
        "id": _doc_id(user_id, date),
        "userId": user_id,
        "date": date,
        "pawseScore": scored.get("pawse_score"),
        "label": scored.get("label"),
        "reasons": scored.get("reasons", []),
        "recommendations": scored.get("recommendations", []),
        "calendarSource": scored.get("calendar_source"),
        "mode": scored.get("mode"),
        "scored": scored,
    }
    container.upsert_item(document)


def get_day(user_id: str, date: str) -> dict[str, Any] | None:
    """Return the stored scored day, or None if absent/unconfigured."""
    container = _connect()
    if container is None:
        return None

    from azure.cosmos import exceptions

    try:
        item = container.read_item(item=_doc_id(user_id, date), partition_key=user_id)
        return item.get("scored")
    except exceptions.CosmosResourceNotFoundError:
        return None


def list_history(user_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Return up to ``days`` most-recent scored days for a user (newest first)."""
    container = _connect()
    if container is None:
        return []

    query = (
        "SELECT TOP @days c.date, c.pawseScore, c.label "
        "FROM c WHERE c.userId = @userId ORDER BY c.date DESC"
    )
    items = container.query_items(
        query=query,
        parameters=[
            {"name": "@days", "value": days},
            {"name": "@userId", "value": user_id},
        ],
        partition_key=user_id,
    )
    return list(items)
