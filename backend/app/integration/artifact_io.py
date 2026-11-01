"""Bounded, non-executing decoding of native scientific archive artifacts."""

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import PurePosixPath

from .scienceclaw.adapters.base import ToolFailed, ToolUnavailable

ALLOWED = {
    ".pdb",
    ".cif",
    ".mmcif",
    ".json",
    ".sdf",
    ".csv",
    ".xvg",
    ".mdout",
    ".prmtop",
    ".gro",
    ".xtc",
    ".trr",
    ".dcd",
    ".nc",
    ".pdbqt",
    ".fasta",
    ".fa",
    ".log",
}


def expand_archives(result, out, byte_limit, redact):
    additions, total, count = [], 0, 0
    for index, artifact in enumerate(list(result.get("artifacts", []))):
        if not artifact.get("hash_verified") or not artifact["filename"].endswith(
            (".tar.gz", ".tgz", ".zip", ".tar")
        ):
            continue
        raw = (out / artifact["filename"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
            raise ToolFailed("ARCHIVE_HASH_MISMATCH", "Native archive bytes changed.")
        rows = []
        if artifact["filename"].endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ToolFailed("UNSAFE_RESULT_ARCHIVE", "Archive links are forbidden.")
                    if len(rows) >= 256 or sum(r[1] for r in rows) + item.file_size > byte_limit:
                        raise ToolUnavailable(
                            "RESULT_ARCHIVE_LIMIT", "Native archive exceeds audit limits."
                        )
                    rows.append((item.filename, item.file_size, lambda i=item: archive.read(i)))
                additions, total, count = decode(
                    rows, artifact, index, out, byte_limit, redact, additions, total, count
                )
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
                for item in archive:
                    if item.isdir():
                        continue
                    if not item.isfile():
                        raise ToolFailed(
                            "UNSAFE_RESULT_ARCHIVE", "Archive links/special files are forbidden."
                        )
                    if len(rows) >= 256 or sum(r[1] for r in rows) + item.size > byte_limit:
                        raise ToolUnavailable(
                            "RESULT_ARCHIVE_LIMIT", "Native archive exceeds audit limits."
                        )
                    rows.append(
                        (item.name, item.size, lambda i=item: archive.extractfile(i).read())
                    )
                additions, total, count = decode(
                    rows, artifact, index, out, byte_limit, redact, additions, total, count
                )
    result["artifacts"].extend(additions)
    return result


def decode(rows, parent, index, out, limit, redact, additions, total, count):
    names = set()
    for name, size, reader in rows:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) in names:
            raise ToolFailed("UNSAFE_RESULT_ARCHIVE", "Unsafe/duplicate archive member path.")
        names.add(str(path))
        total += size
        count += 1
        if total > limit or count > 256:
            raise ToolUnavailable("RESULT_ARCHIVE_LIMIT", "Native archive exceeds audit limits.")
        if path.suffix.lower() not in ALLOWED:
            continue
        data = reader()
        if len(data) != size or any(v.encode() in data for v in redact.secrets):
            raise ToolFailed(
                "INVALID_RESULT_ARCHIVE", "Native member size or credential check failed."
            )
        stem = PurePosixPath(parent["filename"]).name.split(".")[0]
        filename = f"{stem}_native_{index}_{count}{path.suffix.lower()}"
        with (out / filename).open("xb") as handle:
            handle.write(data)
        document = json.loads(data) if path.suffix.lower() == ".json" else None
        if document is not None:
            json.dumps(document, allow_nan=False)
        additions.append(
            {
                "filename": filename,
                "source_member": str(path),
                "parent_archive_sha256": parent["sha256"],
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "hash_verified": True,
                "data": document,
                "format_validated": document is not None,
            }
        )
    return additions, total, count
