"""MCP client for the Nebius Scientific AI server.

That server carries the engines this project has no local install of — DiffDock,
AlphaFold 3, OpenFold, ESMFold, GROMACS, AMBER, OpenMM, ADMET-AI and molecule
generation — behind a streamable-HTTP MCP endpoint. Calling it as an MCP client gives
typed arguments and structured results, rather than driving a chat agent and parsing
prose out of it.

Its own instructions set the contract for the heavy tools: upload immutable inputs,
submit once with an idempotency key, poll the returned operation id, then fetch the
artifact. Small jobs can instead pass ``wait_seconds`` and get the result inline.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings

logger = logging.getLogger(__name__)


class NebiusNotConfiguredError(Exception):
    """No API key, so the remote engines cannot be reached."""


class NebiusError(Exception):
    """The remote server refused a call or returned something unusable."""


@dataclass(frozen=True)
class RemoteTool:
    name: str
    description: str


class NebiusClient:
    """Thin wrapper over the remote MCP server.

    A session is opened per call. The server is remote and the heavy work is durable and
    polled, so holding a long-lived session buys little and risks a stale connection.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.scientific_models_api_key)

    def _require_key(self) -> str:
        key = self.settings.scientific_models_api_key
        if not key:
            raise NebiusNotConfiguredError(
                "No Nebius key. Set NEBIUS_API_KEY (or SCIENTIFIC_MODELS_API_KEY) in "
                "backend/.env to reach the remote structural engines."
            )
        return key

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Client]:
        key = self._require_key()
        headers = {"Authorization": f"Bearer {key}"}
        timeout = httpx.Timeout(self.settings.nebius_timeout_seconds)
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http:
            # The transport is passed un-entered; Client owns its lifecycle.
            transport = streamable_http_client(
                self.settings.scientific_models_mcp_url, http_client=http
            )
            async with Client(transport) as client:
                yield client

    async def list_tools(self) -> list[RemoteTool]:
        """Every tool the remote server exposes."""
        try:
            async with self._session() as client:
                result = await client.list_tools()
        except NebiusNotConfiguredError:
            raise
        except Exception as exc:
            raise NebiusError(f"Could not reach the Nebius MCP server: {exc}") from exc
        return [
            RemoteTool(name=t.name, description=(t.description or "").strip()) for t in result.tools
        ]

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call one remote tool and return its structured result.

        Raises NebiusError when the server reports the call as failed, so a caller never
        mistakes an error payload for a scientific result.
        """
        try:
            async with self._session() as client:
                result = await client.call_tool(tool, arguments)
        except NebiusNotConfiguredError:
            raise
        except Exception as exc:
            raise NebiusError(f"Call to {tool} failed: {exc}") from exc

        if result.is_error:
            text = " ".join(getattr(block, "text", "") for block in (result.content or [])).strip()
            raise NebiusError(f"{tool} reported an error: {text[:400] or 'no detail given'}")

        if result.structured_content is not None:
            return result.structured_content
        # Some tools answer with text blocks only.
        text = " ".join(getattr(block, "text", "") for block in (result.content or [])).strip()
        return {"text": text}
