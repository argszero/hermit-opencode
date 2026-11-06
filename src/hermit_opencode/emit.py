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
import json
import shutil

import yaml

from . import __version__ as CONVERTER_VERSION
from .manifest import AdapterError, read as read_manifest

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

    config = {"$schema": SCHEMA}
    if bundle.has_context:
        (output / CONTEXT).parent.mkdir(parents=True, exist_ok=True)
        (output / CONTEXT).write_text(context.strip() + "\n")
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
            "omitted": omitted, "record": RECORD}
