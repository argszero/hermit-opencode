"""Emit an OpenCode configuration from a hermit adapter.

OpenCode reads its configuration, skills and subagents from the project directory
it is opened in, and that carries every part of an adapter:

- context: `.opencode/context.md`, listed in `opencode.json`'s `instructions`.
  OpenCode combines every instruction file with the project's own `AGENTS.md`, so
  a project that already has rules keeps them.
- tools: an entry in `opencode.json`'s `mcp` map: a server of type `local`, started
  as `hermit serve`.
- skills: `.opencode/skills/`, the directory OpenCode discovers `skills/*/SKILL.md`
  from.
- roles: `.opencode/agents/*.md`, where the file name is the agent's name and the
  frontmatter makes it a subagent (`mode: subagent`).

OpenCode expands no plugin-root variable, so the tool entry may not name an absolute
path: it names the embedded adapter relative to the project root, and OpenCode starts
the server there. The audit log lives under `.opencode/audit/`, outside the adapter.

No `cwd` key is emitted, deliberately. OpenCode 1.1.2's own validator rejects it
(`Unrecognized key: "cwd"`) and refuses the entire configuration with it, even
though the JSON schema opencode.ai publishes still documents the key. Without it the
server starts in the project directory, which is what the entry needs.

This module imports nothing from hermit. The tool server is a string in the emitted
JSON (`hermit serve adapter`), run later by OpenCode, so the converter needs no
hermit at conversion time. A part of the adapter OpenCode cannot carry is refused,
not silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import fnmatch
import json
import posixpath
import re
import shutil

import yaml

from . import __version__ as CONVERTER_VERSION
from .manifest import AdapterError, EXPORTS, MANIFEST_V1, MANIFEST_V2, read as read_manifest

# The adapter travels inside the configuration: a configuration that referenced an
# outside directory would break the moment it was copied anywhere else.
ADAPTER_DIR = "adapter"
# `hermit serve`, not an interpreter path: the host resolves it on PATH wherever
# hermit is installed.
SERVER_COMMAND = "hermit"
AUDIT_LOG = "tool-calls.jsonl"
# This converter's own record, and the only marker that makes an output directory
# ours. It is named for this converter so a `hermit.json` left by `hermit convert`
# never lets this tool clear a directory it did not write.
RECORD = "hermit-opencode.json"

SCHEMA = "https://opencode.ai/config.json"
CONFIG = "opencode.json"
DIR = ".opencode"
CONTEXT = f"{DIR}/context.md"
AUDIT_DIR = f"{DIR}/audit"

IGNORED = ("__pycache__", ".git", "*.pyc")

LISTED_FILES = 60                 # the most files the context lists; the rest are counted


class Unsupported(ValueError):
    """Parts of the adapter OpenCode cannot carry."""


@dataclass(frozen=True)
class Bundle:
    adapter: Path
    manifest: dict
    context: str
    roles: list
    layout: int

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def name(self) -> str:
        return self.manifest.get("name", self.id)

    @property
    def version(self) -> str:
        return self.manifest["version"]

    @property
    def tools(self) -> list:
        hidden = self.manifest.get("context_tool")
        # The context tool is the harness's: a host cannot call it per task.
        return [dict(t) for t in self.manifest.get("tools") or [] if t.get("name") != hidden]

    @property
    def server(self) -> str:
        return self.id.replace("-", "_")

    @property
    def has_context(self) -> bool:
        return bool(self.context.strip())

    @property
    def hooks(self) -> dict | None:
        return _hooks(self.adapter, self.manifest)


def inside(root: Path, relative: str) -> Path:
    """A path named by the adapter, resolved and required to stay inside it."""
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise AdapterError("Adapter entries must be relative paths")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise AdapterError(f"Missing or out-of-repo adapter entry: {relative}")
    return path


def role_body(adapter: Path, role: dict) -> str:
    """A role's instructions, inline or from the file it names."""
    return role.get("body") or inside(adapter, role["instructions"]).read_text()


def subagent_name(name: str) -> str:
    """A role name as the hosts that use this file layout spell it."""
    native = str(name).replace("_", "-")
    if not native or not all(part for part in native.split("-")) or native[0].isdigit():
        raise AdapterError(f"Invalid role name: {name}")
    return native


def _lenient_frontmatter(text: str) -> tuple[dict, str]:
    """Frontmatter read line by line, as Codex-tree harnesses read an AGENT.md."""
    if not text.startswith("---\n") or text.find("\n---", 4) < 0:
        return {}, text
    end = text.find("\n---", 4)
    head = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            value = value.strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                try:
                    value = str(json.loads(value))
                except ValueError:
                    value = value.strip('"')
            else:
                value = value.strip("\"'")
            head[key.strip()] = value
    body = text[end + 4:].lstrip("-").lstrip("\n")
    return head, body


def _summary(path: Path) -> str:
    """One line about a file, from what its author wrote for a reader: the frontmatter
    description, a Markdown or text file's first line of prose (comments left out), or a
    Python file's docstring or leading comment; else nothing, because the first line of
    code says nothing about the file."""
    try:
        text = path.read_text(encoding="utf-8")[:4000]
    except (OSError, UnicodeDecodeError):
        return ""
    head, body = _lenient_frontmatter(text)
    line = str(head.get("description") or "")
    if not line and path.suffix in (".md", ".txt", ""):
        prose = re.sub(r"<!--.*?(-->|$)", "", body, flags=re.S)
        line = next((s.strip() for s in prose.splitlines() if s.strip()), "")
    elif not line and path.suffix == ".py":
        doc = re.match(r'\s*(?:#![^\n]*\n\s*)?(?:[rRuU]?("""|\'\'\')\s*(?P<doc>[^\n]*)|#\s*(?P<comment>[^\n]*))', text)
        line = (doc.group("doc") or doc.group("comment") or "") if doc else ""
    line = re.sub(r'^[#>*\-\s]+|[`]|("""|\'\'\')$', "", line).strip()
    return line[:117] + "..." if len(line) > 120 else line


def folder_note(folder: str) -> str:
    """The line above the adapter's context that says where its files are, and that the
    paths inside it are relative to that folder."""
    return (f"This adapter's files are in `{folder}/`. Paths in the instructions below, and in the "
            f"adapter's skills and roles, are relative to that folder: run a command they give from "
            f"there (`cd {folder} && ...`).")


def other_files_section(bundle: Bundle, folder: str, names: list) -> str:
    """The context's list of the files no export connects, each with the line its author
    wrote for a reader, under the folder the adapter is embedded at."""
    listed = [f"- `{folder}/{name}`" + (f": {summary}" if (summary := _summary(bundle.adapter / name)) else "")
              for name in names[:LISTED_FILES]]
    if len(names) > LISTED_FILES:
        listed.append(f"- and {len(names) - LISTED_FILES} more files under `{folder}/`")
    return "Other files of this adapter (read one when it is relevant):\n" + "\n".join(listed)


def adapter_context(bundle: Bundle, folder: str, context: str, unnamed: list) -> str:
    """The context this tool writes: where the adapter's files are, then the adapter's own
    context, then the files no export connects.

    The same three parts, in the same order, are what a `hermit deploy` workspace's context
    is built from (`hermit/hosts/opencode.py:53`: `folder_note`, the rendered context, then
    `resources`). The report's `unnamed_files` is read by whoever runs the conversion; this
    file is what the session itself reads when it starts, so a file named only in the report
    is a file nothing that acts has been told about.
    """
    parts = [folder_note(folder)]
    if bundle.has_context:
        parts.append(context.strip())
    if unnamed:
        parts.append(other_files_section(bundle, folder, unnamed))
    return "\n\n".join(parts) + "\n"


def subagent_files(root: Path, directory: str) -> list:
    """One entry per subagent: `<name>.md` with name and description in frontmatter,
    or `<name>/AGENT.md`, named by its directory."""
    out = []
    base = root / directory
    if not base.is_dir():
        raise AdapterError(f"The adapter declares agents at {directory}, which is not a directory")
    for path in sorted(p for p in base.glob("*.md") if p.name != "README.md"):
        text = path.read_text()
        if not text.startswith("---\n") or "\n---" not in text[4:]:
            raise AdapterError(f"{path.relative_to(root)}: a subagent file starts with YAML frontmatter")
        end = text.index("\n---", 4)
        head = yaml.safe_load(text[4:end]) or {}
        body = text[end + 4:].lstrip("-").lstrip("\n")
        if not isinstance(head, dict) or not head.get("name") or not head.get("description"):
            raise AdapterError(f"{path.relative_to(root)}: frontmatter needs name and description")
        out.append({"name": str(head["name"]), "description": str(head["description"]),
                    "instructions": path.relative_to(root).as_posix(), "body": body})
    for path in sorted(base.glob("*/AGENT.md")):
        head, body = _lenient_frontmatter(path.read_text(errors="replace"))
        name = path.parent.name
        out.append({"name": name, "description": head.get("description") or name,
                    "instructions": path.relative_to(root).as_posix(), "body": body})
    return out


def _hooks(adapter: Path, manifest: dict) -> dict | None:
    declared = manifest.get("hooks")
    if not isinstance(declared, str) or Path(declared).is_absolute():
        return None
    path = (adapter / declared).resolve()
    if not path.is_relative_to(adapter.resolve()) or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise AdapterError(f"{declared} is not JSON: {exc}") from None
    events = data.get("hooks") if isinstance(data, dict) else None
    return events if isinstance(events, dict) and events else None


def load(adapter: Path) -> Bundle:
    """Read an adapter into the parts this emitter writes."""
    adapter = Path(adapter).resolve()
    manifest = read_manifest(adapter)
    if not manifest.get("plugin-portable", True):
        why = (f"; its context tool `{manifest['context_tool']}` adds context per task, which the harness computes "
               "before the agent's first model call, and an installed configuration has no such moment"
               if manifest.get("context_tool") else "")
        raise Unsupported(f"An OpenCode configuration cannot carry the {manifest['id']} adapter: its template "
                          f"declares plugin-portable: false{why}. Use it through hermit (train, eval or a Session).")
    context_path = adapter / manifest["context"]
    context = context_path.read_text() if context_path.is_file() else ""
    declaration = manifest.get("agents")
    roles = subagent_files(adapter, declaration) if isinstance(declaration, str) else []
    names = set()
    for role in roles:
        if role["name"] in names:
            raise AdapterError(f"Duplicate exported role: {role['name']}")
        names.add(role["name"])
    return Bundle(adapter, manifest, context, roles, manifest["layout"])


def prepare_output(output: Path, adapter: Path, own_file: str) -> Path:
    """The output directory: outside the adapter, and empty unless an earlier run of
    this converter wrote `own_file` there."""
    output = Path(output).resolve()
    if output == adapter or adapter in output.parents or output in adapter.parents:
        raise ValueError("The configuration must be written outside the adapter")
    if output.exists() and any(output.iterdir()) and not (output / own_file).is_file():
        raise ValueError("Refusing to write into a nonempty directory this converter did not create")
    output.mkdir(parents=True, exist_ok=True)
    return output


def clear(root: Path, *names: str) -> None:
    """Remove the generated entries of an earlier run, so a part the adapter no longer
    has (a skill, a role, the context) does not survive. The user's audit log stays."""
    for name in names:
        path = root / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def embed_adapter(bundle: Bundle, root: Path) -> Path:
    """Copy the adapter in, so the configuration is self-contained."""
    target = root / ADAPTER_DIR
    clear(root, ADAPTER_DIR)
    shutil.copytree(bundle.adapter, target, ignore=shutil.ignore_patterns(*IGNORED), symlinks=True)
    return target


def _norm(relative: str) -> str:
    """An adapter path as one name, with `./` and `..` resolved: what a manifest entry and
    a file's own relative path have to agree on to be recognisable as the same file."""
    name = posixpath.normpath(str(relative).replace("\\", "/"))
    return "" if name == "." else name


def unnamed_files(bundle: Bundle) -> list:
    """The adapter's files that the emitted configuration connects nothing to.

    What the configuration reaches is finite and known when it is written: the context,
    the manifest `hermit serve` reads, the directories the skills and roles come from,
    each tool's entrypoint, and a declared hooks file. A file none of those reaches is
    copied into `adapter/` all the same, and no part of the output names it — a session
    finds it only if something tells it to look. hermit's own plugins report the same
    list, under this name, since `42fbd08`; this tool names what its own emission
    reaches, which includes the whole of `.hermit/` because it carries the whole adapter.
    """
    adapter = bundle.adapter
    manifest = bundle.manifest
    connected = {_norm(MANIFEST_V1), _norm(MANIFEST_V2), _norm(EXPORTS), _norm(manifest["context"])}
    directories = []
    skills = manifest.get("skills")
    if isinstance(skills, str):
        source = (adapter / skills).resolve()
        # Only a directory holding a SKILL.md is exported, so only then is the tree connected.
        if source.is_dir() and any((child / "SKILL.md").is_file() for child in source.iterdir()):
            directories.append(f"{_norm(skills)}/")
    if isinstance(manifest.get("agents"), str):
        directories.append(f"{_norm(manifest['agents'])}/")
    if isinstance(manifest.get("hooks"), str):
        connected.add(_norm(manifest["hooks"]))
    for tool in bundle.tools:
        entrypoint = tool.get("entrypoint")
        if isinstance(entrypoint, str):
            connected.add(_norm(entrypoint.partition(":")[0]))
    internal = [_norm(p) for p in manifest.get("internal") or [] if isinstance(p, str)]
    document = adapter / manifest["context"]
    context = document.read_bytes() if document.is_file() else None
    out = []
    for path in sorted(p for p in adapter.rglob("*") if p.is_file()):
        relative = path.relative_to(adapter)
        name = relative.as_posix()
        if any(part in IGNORED for part in relative.parts) or name.endswith(".pyc"):
            continue                                    # the copy leaves it out: naming it would be false
        if context is not None and path.stat().st_size == len(context) and path.read_bytes() == context:
            continue                                    # a copy of the context: already carried as it
        if name in connected or any(name.startswith(folder) for folder in directories):
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in internal):
            continue                                    # the harness's own, not the session's
        out.append(name)
    return out


def copy_skills(bundle: Bundle, target: Path) -> list:
    """Every skill directory (one holding SKILL.md) under the adapter's `skills`."""
    declared = bundle.manifest.get("skills")
    if not declared:
        return []
    source = (bundle.adapter / declared).resolve()
    names = []
    if source.is_dir():
        for child in sorted(source.iterdir()):
            if (child / "SKILL.md").is_file():
                shutil.copytree(child, target / child.name, dirs_exist_ok=True, symlinks=True)
                names.append(child.name)
    return names


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def agent_file(role: dict, instructions: str) -> tuple[str, str]:
    """A role as an OpenCode subagent. The file name is the agent's name, so the
    frontmatter carries only what OpenCode does not derive from it."""
    native = subagent_name(role["name"])
    return native, (f"---\ndescription: {json.dumps(role['description'])}\nmode: subagent\n---\n\n"
                    f"{instructions.strip()}\n")


def build(adapter: Path, output: Path, *, allow_lossy: bool = False) -> dict:
    """Convert the adapter at `adapter` into an OpenCode configuration at `output`."""
    bundle = load(adapter)
    if bundle.hooks and not allow_lossy:
        events = ", ".join(bundle.hooks)
        raise Unsupported(f"An OpenCode configuration cannot carry these parts of the {bundle.id} adapter:\n"
                          f"- hooks: no host configuration carries an adapter's lifecycle hooks yet ({events}); "
                          "connect them in a workspace with `hermit deploy --host codex` or `--host claude-code`\n"
                          "Pass --allow-lossy to emit the configuration without them.")
    omitted = ["hooks"] if bundle.hooks else []

    output = prepare_output(Path(output), bundle.adapter, RECORD)
    # Only the generated entries: the audit log of an earlier conversion is the user's and stays.
    clear(output, f"{DIR}/skills", f"{DIR}/agents", CONTEXT)

    roles = {}
    for role in bundle.roles:
        native, text = agent_file(role, role_body(bundle.adapter, role))
        (output / DIR / "agents").mkdir(parents=True, exist_ok=True)
        (output / DIR / "agents" / f"{native}.md").write_text(text)
        roles[role["name"]] = native

    context = bundle.context
    for name, native in roles.items():
        context = context.replace(f"`{name}`", f"`{native}`")
    # Written only when the adapter has a context, as before; what it carries that no export
    # connects is named inside it rather than in a file of its own, because the report that
    # lists them is read by whoever converts, and this file is read by the session.
    unnamed = unnamed_files(bundle)

    config = {"$schema": SCHEMA}
    if bundle.has_context:
        (output / CONTEXT).parent.mkdir(parents=True, exist_ok=True)
        (output / CONTEXT).write_text(adapter_context(bundle, ADAPTER_DIR, context, unnamed))
        config["instructions"] = [CONTEXT]
    if bundle.tools:
        (output / AUDIT_DIR).mkdir(parents=True, exist_ok=True)
        config["mcp"] = {bundle.server: {
            "type": "local",
            "command": [SERVER_COMMAND, "serve", ADAPTER_DIR, "--audit-log", f"{AUDIT_DIR}/{AUDIT_LOG}"],
            "enabled": True}}  # no `cwd`: opencode 1.1.2 rejects the key, see the docstring
    write_json(output / CONFIG, config)

    skills = copy_skills(bundle, output / DIR / "skills")
    embed_adapter(bundle, output)
    record = {"adapter": bundle.id, "adapter_version": bundle.version, "layout": bundle.layout,
              "converter": f"hermit-opencode {CONVERTER_VERSION}"}
    write_json(output / RECORD, record)
    return {"target": "opencode", "adapter_id": bundle.id, "version": bundle.version, "layout": bundle.layout,
            "output": str(output), "plugin": str(output),
            "install": [f"cp -R {output}/. /path/to/your/project/", "cd /path/to/your/project && opencode"],
            "context": CONTEXT if bundle.has_context else None,
            "skills": skills, "roles": roles,
            "server_name": bundle.server if bundle.tools else None,
            "tools": [t["name"] for t in bundle.tools],
            "omitted": omitted, "unnamed_files": unnamed, "record": RECORD}
