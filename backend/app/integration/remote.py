"""Bounded Nebius operations with durable receipts and verified artifact bytes."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator

from app.nebius.service import _unwrap

from .privacy import Redactor
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def operation_state(value):
    op = value.get("operation") or {}
    error = value.get("error") or {}
    state = str(op.get("status") or value.get("status") or "").upper()
    operation_id = (
        op.get("id")
        or op.get("operation_id")
        or value.get("operation_id")
        or (error.get("operation_id") if isinstance(error, dict) else None)
    )
    return state, operation_id


class RemoteRunner:
    def __init__(self, settings, client, out, run_id):
        self.settings, self.client, self.out, self.run_id = settings, client, out, run_id
        self.redact = Redactor(settings)

    def save(self, filename, data):
        with (self.out / filename).open("x") as f:
            json.dump(self.redact(data), f, indent=2, allow_nan=False)

    async def execute(self, agent, tool, arguments, operation_id=None):
        tools = {t.name: t for t in await self.client.list_tools()}
        if tool not in tools:
            raise ToolUnavailable("NEBIUS_TOOL_UNAVAILABLE", "Required Nebius model absent.")
        schema = tools[tool].input_schema
        if not schema:
            raise ToolUnavailable("NEBIUS_SCHEMA_REQUIRED", "No advertised model input schema.")
        args = dict(arguments)
        if "idempotency_key" in schema.get("properties", {}):
            args["idempotency_key"] = f"{self.run_id}-{agent}"
        if "wait_seconds" in schema.get("properties", {}):
            args["wait_seconds"] = 0
        Draft202012Validator(schema).validate(args)
        self.save(
            f"{agent}_submission.json",
            {
                "provider": "nebius",
                "tool": tool,
                "arguments": args,
                "schema": schema,
                "input_sha256": hashlib.sha256(
                    json.dumps(args, sort_keys=True).encode()
                ).hexdigest(),
                "resumed_operation_id": operation_id,
            },
        )
        if operation_id:
            payload = _unwrap(
                await self.client.call("get_operation", {"operation_id": operation_id})
            )
        else:
            payload = _unwrap(await self.client.call(tool, args, allow_pending=True))
        self.save(f"{agent}_submission_response.json", payload)
        state, returned_id = operation_state(payload)
        operation_id = returned_id or operation_id
        if operation_id:
            self.save(f"{agent}_operation.json", {"tool": tool, "operation_id": operation_id})
        if payload.get("error") and not operation_id:
            envelope = payload["error"]
            code = str(envelope.get("code", "")) if isinstance(envelope, dict) else ""
            if any(word in code.upper() for word in ("ADMISSION", "UNAVAILABLE", "NOT_READY")):
                raise ToolUnavailable(
                    "NEBIUS_NOT_ADMITTED", "Nebius did not admit scientific work."
                )
            raise ToolFailed("NEBIUS_SUBMISSION_FAILED", "Nebius rejected scientific submission.")
        deadline = time.monotonic() + self.settings.agent_remote_wait_seconds
        sequence = 0
        while operation_id and state not in {
            "SUCCEEDED",
            "SUCCESS",
            "COMPLETED",
            "COMPLETE",
            "FAILED",
            "ERROR",
            "CANCELLED",
            "CANCELED",
        }:
            if time.monotonic() >= deadline:
                return {
                    "status": "PENDING",
                    "tool": tool,
                    "operation_id": operation_id,
                    "detail": "Nebius operation pending; resume polls the same operation.",
                }
            await asyncio.sleep(self.settings.agent_poll_interval_seconds)
            payload = _unwrap(
                await self.client.call("get_operation", {"operation_id": operation_id})
            )
            self.save(f"{agent}_poll_{sequence}.json", payload)
            sequence += 1
            state, _ = operation_state(payload)
        if state in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise ToolFailed("NEBIUS_OPERATION_FAILED", "Nebius operation did not succeed.")
        if operation_id:
            payload = _unwrap(
                await self.client.call("get_operation_result", {"operation_id": operation_id})
            )
        self.save(f"{agent}_remote_result.json", payload)
        if payload.get("error"):
            raise ToolFailed("NEBIUS_RESULT_ERROR", "Nebius returned an error instead of a result.")
        # An inline success must be explicit. A polled success is already attested above.
        if not operation_id and state not in {"SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE"}:
            raise ToolUnavailable(
                "NEBIUS_OUTPUT_UNVERIFIED", "No completed operation was verified."
            )
        pointers = [v for v in objects(payload) if v.get("artifact_id")]
        if not pointers:
            raise ToolUnavailable(
                "NEBIUS_ARTIFACT_REQUIRED", "Completed job has no artifact pointer."
            )
        artifacts, seen = [], set()
        for pointer in pointers:
            artifact_id = pointer["artifact_id"]
            if artifact_id in seen:
                continue
            seen.add(artifact_id)
            artifacts.append(await self.retrieve(agent, pointer, len(artifacts)))
        return {
            "status": "SUCCEEDED",
            "tool": tool,
            "operation_id": operation_id,
            "artifacts": artifacts,
            "remote": self.redact(payload),
        }

    async def retrieve(self, agent, pointer, index):
        artifact_id = pointer["artifact_id"]
        metadata = _unwrap(
            await self.client.call("get_scientific_artifact", {"artifact_id": artifact_id})
        )
        candidates = [pointer, *objects(metadata)]
        digest = next((v["sha256"] for v in candidates if v.get("sha256")), None)
        size = next((v["size_bytes"] for v in candidates if v.get("size_bytes") is not None), None)
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(size, int):
            raise ToolUnavailable(
                "ARTIFACT_HASH_REQUIRED", "Artifact has no digest and byte count."
            )
        if not 0 < size <= self.settings.agent_max_artifact_bytes:
            raise ToolUnavailable(
                "ARTIFACT_SIZE_LIMIT", "Artifact exceeds the configured byte limit."
            )
        handle = _unwrap(
            await self.client.call("download_scientific_artifact", {"artifact_id": artifact_id})
        )
        url = (handle.get("handle") or {}).get("url") or handle.get("download_url")
        parsed = urlparse(url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ToolFailed("INVALID_ARTIFACT_URL", "Artifact download must use public HTTPS.")
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
        if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ToolFailed(
                "INVALID_ARTIFACT_HOST", "Private artifact download hosts are refused."
            )
        # Separate client: never forward the MCP bearer credential or follow redirects.
        chunks, count = [], 0
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as http:
            async with http.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    count += len(chunk)
                    if count > size or count > self.settings.agent_max_artifact_bytes:
                        raise ToolFailed(
                            "ARTIFACT_SIZE_MISMATCH", "Artifact exceeded its declared size."
                        )
                    chunks.append(chunk)
        data = b"".join(chunks)
        if count != size or hashlib.sha256(data).hexdigest() != digest:
            raise ToolFailed(
                "ARTIFACT_HASH_MISMATCH", "Downloaded bytes do not match the artifact digest."
            )
        if any(secret.encode() in data for secret in self.redact.secrets):
            raise ToolFailed(
                "ARTIFACT_CONTAINS_SECRET", "Credential-bearing artifact was rejected."
            )
        filename = f"{agent}_artifact_{index}.json"
        # Scientific JSON is parsed before publishing; trajectories need a separate parser.
        document = json.loads(data)
        json.dumps(document, allow_nan=False)
        with (self.out / filename).open("xb") as f:
            f.write(data)
        return {
            "artifact_id": artifact_id,
            "sha256": digest,
            "size_bytes": size,
            "filename": filename,
            "data": document,
            "hash_verified": True,
        }
