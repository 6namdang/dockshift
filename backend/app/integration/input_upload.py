"""Explicitly authorized immutable input upload; never submits scientific jobs.

The native manifest document is caller-authored against the provider's contract.
No artifact IDs, archive roles or biological parameters are invented here.
"""

import asyncio
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator

from app.nebius.service import _unwrap

from .remote import objects
from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable


async def upload_input(client, settings, path, model_id, media_type, approved_by):
    if not settings.agent_compute_enabled or not approved_by:
        raise ToolUnavailable(
            "INPUT_UPLOAD_APPROVAL_REQUIRED", "Input publishing remains explicitly opt-in."
        )
    data = path.read_bytes()
    if not 0 < len(data) <= settings.agent_max_artifact_bytes:
        raise ToolUnavailable("INPUT_SIZE_LIMIT", "Upload exceeds the configured limit.")
    from .privacy import Redactor

    if any(secret.encode() in data for secret in Redactor(settings).secrets):
        raise ToolFailed("INPUT_CONTAINS_SECRET", "Credential-bearing input rejected.")
    digest = hashlib.sha256(data).hexdigest()
    tools = {t.name: t for t in await client.list_tools()}
    begin = {
        "model_id": model_id,
        "sha256": digest,
        "size_bytes": len(data),
        "media_type": media_type,
        "compression": "none",
        "idempotency_key": f"dockshift-input-{model_id}-{digest}",
    }
    schema = tools.get("begin_scientific_artifact_upload")
    if schema is None or not schema.input_schema:
        raise ToolUnavailable("UPLOAD_SCHEMA_REQUIRED", "Native upload schema unavailable.")
    Draft202012Validator(schema.input_schema).validate(begin)
    reservation = _unwrap(await client.call("begin_scientific_artifact_upload", begin))
    upload_id = next((n["upload_id"] for n in objects(reservation) if n.get("upload_id")), None)
    handles = [n for n in objects(reservation) if n.get("url") or n.get("upload_url")]
    if not upload_id or len(handles) != 1:
        raise ToolUnavailable(
            "UPLOAD_HANDLE_UNSUPPORTED", "Native upload handle layout needs qualification."
        )
    handle = handles[0]
    url = handle.get("url") or handle["upload_url"]
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or handle.get("method", "PUT") != "PUT"
    ):
        raise ToolFailed("INVALID_UPLOAD_HANDLE", "Upload requires a public HTTPS PUT URL.")
    addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ToolFailed("INVALID_UPLOAD_HOST", "Private upload hosts are refused.")
    headers = {"Content-Type": media_type}
    for key, value in handle.get("headers", {}).items():
        if key.lower() not in ("content-type", "x-amz-checksum-sha256", "content-md5"):
            raise ToolUnavailable(
                "UPLOAD_HEADERS_UNSUPPORTED",
                "Unexpected native upload header; credential forwarding refused.",
            )
        headers[key] = value
    # No MCP authentication, ambient proxy credentials or redirect forwarding.
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=120) as http:
        response = await http.put(url, content=data, headers=headers)
        if response.status_code not in (200, 201, 204):
            raise ToolFailed("INPUT_TRANSFER_FAILED", "Immutable scientific input transfer failed.")
    finalized = _unwrap(
        await client.call("finalize_scientific_artifact_upload", {"upload_id": upload_id})
    )
    refs = [
        n
        for n in objects(finalized)
        if n.get("artifact_id") and n.get("sha256") == digest and n.get("size_bytes") == len(data)
    ]
    if len(refs) != 1:
        raise ToolUnavailable(
            "UPLOAD_FINALIZATION_UNVERIFIED", "Finalization did not verify the exact input bytes."
        )
    return {
        k: refs[0].get(k)
        for k in ("artifact_id", "sha256", "size_bytes", "media_type", "compression")
        if refs[0].get(k) is not None
    }


async def main():
    import argparse
    import json
    from pathlib import Path

    from app.config import Settings
    from app.nebius.client import NebiusClient
    from app.structural import StructuralService

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--model", required=True)
    parser.add_argument("--media-type", required=True)
    parser.add_argument("--reviewed-by")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    path = StructuralService(settings).store.resolve_input(args.input)
    if not args.publish:
        print(
            json.dumps(
                {
                    "status": "BLOCKED_UNTIL_EXPLICIT_PUBLISH",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size,
                    "upload_performed": False,
                }
            )
        )
        return
    result = await upload_input(
        NebiusClient(settings), settings, Path(path), args.model, args.media_type, args.reviewed_by
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
