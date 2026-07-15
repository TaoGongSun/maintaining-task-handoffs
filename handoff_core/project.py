from __future__ import annotations

import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .atomic import write_json
from .document import DocumentError


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ProjectIdentity:
    project_id: str
    name: str
    remote: str | None


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise DocumentError("invalid_project")
    return project_id


def parse_project_identity(value: dict[str, object]) -> ProjectIdentity:
    if value.get("version") != 1:
        raise DocumentError("invalid_project")
    project_id = value.get("id")
    name = value.get("name")
    remote = value.get("remote")
    if not isinstance(project_id, str) or not isinstance(name, str):
        raise DocumentError("invalid_project")
    if not project_id.strip() or not name.strip():
        raise DocumentError("invalid_project")
    validate_project_id(project_id)
    if remote is not None and not isinstance(remote, str):
        raise DocumentError("invalid_project")
    return ProjectIdentity(project_id, name, remote)


def _remote_parts(value: str) -> tuple[str, str] | None:
    scp = re.fullmatch(r"(?:[^@]+@)?([^:]+):(.+)", value)
    if scp and "://" not in value:
        host, path = scp.groups()
    else:
        parsed = urlparse(value)
        if not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    clean = path.strip("/").removesuffix(".git")
    if not clean:
        return None
    return host.casefold(), clean.casefold()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-")


def _git_origin(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _valid_identity(data: object) -> ProjectIdentity | None:
    if not isinstance(data, dict):
        return None
    try:
        return parse_project_identity(data)
    except DocumentError:
        return None


def load_or_create_project(root: Path) -> ProjectIdentity:
    path = root / ".ai" / "project.json"
    try:
        existing = _valid_identity(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
        existing = None
    if existing is not None:
        return existing

    remote = _git_origin(root)
    if remote:
        parts = _remote_parts(remote)
        if parts is not None:
            host, clean = parts
            project_id = _slug(f"{host}/{clean}")
            name = Path(clean).name or root.name
            identity = ProjectIdentity(project_id, name, remote)
            write_json(
                path,
                {
                    "version": 1,
                    "id": identity.project_id,
                    "name": identity.name,
                    "remote": identity.remote,
                },
            )
            return identity

    project_id = f"local-{uuid.uuid4().hex}"
    identity = ProjectIdentity(project_id, root.name, None)
    write_json(
        path,
        {
            "version": 1,
            "id": identity.project_id,
            "name": identity.name,
            "remote": identity.remote,
        },
    )
    return identity
