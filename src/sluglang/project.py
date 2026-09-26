from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .diagnostics import SemanticError

MANIFEST_NAME = "slug.json"


def _reject_noncanonical_json_escapes(text: str) -> None:
    """Keep the reference parser aligned with the native schema-1 manifest parser.

    K9E manifests deliberately use canonical JSON strings: only quote, reverse-solidus,
    and solidus escapes are accepted. Names and paths have a narrower contract than
    arbitrary JSON text, so accepting alternate spellings such as ``\u006d`` in only
    one implementation would create two textual identities for the same project.
    """
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == '"':
            in_string = False
            i += 1
            continue
        if ch == "\\":
            i += 1
            if i >= len(text) or text[i] not in {'"', "\\", "/"}:
                raise ValueError("project manifest uses unsupported string escape")
            i += 1
            continue
        i += 1


def _pairs_no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate manifest key {key}")
        out[key] = value
    return out


def _name(value: object, *, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticError(f"project manifest {what} must be a non-empty string")
    if len(value) > 64 or not ("a" <= value[0] <= "z"):
        raise SemanticError(f"project manifest {what} must match [a-z][a-z0-9-]*")
    for ch in value:
        if not ("a" <= ch <= "z" or "0" <= ch <= "9" or ch == "-"):
            raise SemanticError(f"project manifest {what} must match [a-z][a-z0-9-]*")
    return value


def _relative(value: object, *, what: str, source_file: bool) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticError(f"project manifest {what} must be a non-empty relative path")
    if "\\" in value or value.startswith("/") or ":" in value:
        raise SemanticError(f"project manifest {what} must use a project-relative forward-slash path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SemanticError(f"project manifest {what} contains a non-canonical path segment")
    if source_file and not value.endswith(".slg"):
        raise SemanticError(f"project manifest {what} must name an exact .slg source file")
    return value


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    manifest_path: Path
    root: Path
    name: str
    entry: str
    dependencies: dict[str, str]

    @property
    def entry_path(self) -> Path:
        return self.root / self.entry

    @property
    def build_root(self) -> Path:
        return self.root / "build"

    def default_output(self, *, windows: bool = False) -> Path:
        return self.build_root / (self.name + (".exe" if windows else ""))

    def resolve_dependency(self, spec: str) -> Path:
        if not spec.startswith("@dep/"):
            raise SemanticError("internal project resolver received a non-dependency URI")
        tail = spec[5:]
        if "/" not in tail:
            raise SemanticError("dependency import must be @dep/<name>/<exact-file.slg>")
        name, rel = tail.split("/", 1)
        _name(name, what="dependency import name")
        rel = _relative(rel, what="dependency import path", source_file=True)
        root = self.dependencies.get(name)
        if root is None:
            raise SemanticError(f"undeclared project dependency {name}")
        return self.root / root / rel


def load_project_manifest(path: str | Path) -> ProjectManifest:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SemanticError(f"cannot read project manifest {path}: {exc}") from exc
    try:
        _reject_noncanonical_json_escapes(text)
        data = json.loads(text, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SemanticError(f"invalid project manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SemanticError("project manifest root must be an object")
    allowed = {"schema", "name", "entry", "dependencies"}
    unknown = set(data) - allowed
    if unknown:
        raise SemanticError(f"unknown project manifest field {sorted(unknown)[0]}")
    if data.get("schema") != 1 or isinstance(data.get("schema"), bool):
        raise SemanticError("project manifest schema must be 1")
    if "name" not in data or "entry" not in data:
        raise SemanticError("project manifest requires name and entry")
    name = _name(data["name"], what="name")
    entry = _relative(data["entry"], what="entry", source_file=True)
    raw_deps = data.get("dependencies", {})
    if not isinstance(raw_deps, dict):
        raise SemanticError("project manifest dependencies must be an object")
    deps: dict[str, str] = {}
    for dep_name, dep_root in raw_deps.items():
        key = _name(dep_name, what="dependency name")
        deps[key] = _relative(dep_root, what=f"dependency {key}", source_file=False)
    return ProjectManifest(path, path.parent, name, entry, deps)


def discover_project_manifest(start: str | Path, *, is_file: bool) -> Path | None:
    p = Path(start)
    directory = p.parent if is_file else p
    if not directory.is_absolute():
        directory = (Path.cwd() / directory).resolve()
    else:
        directory = directory.resolve()
    while True:
        candidate = directory / MANIFEST_NAME
        if candidate.is_file():
            return candidate
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


def project_for_source(path: str | Path) -> ProjectManifest | None:
    manifest = discover_project_manifest(path, is_file=True)
    return None if manifest is None else load_project_manifest(manifest)


def discover_project(start: str | Path | None = None) -> ProjectManifest | None:
    manifest = discover_project_manifest(Path.cwd() if start is None else start, is_file=False)
    return None if manifest is None else load_project_manifest(manifest)
