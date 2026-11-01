from dataclasses import asdict

from ..contracts import ArtifactRef


def ref(path, role=None):
    return asdict(ArtifactRef.of(path, role))
