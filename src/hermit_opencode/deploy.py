"""Deploy an adapter into an OpenCode workspace, in place.

`convert` writes a configuration into a directory of its own that the user then
copies into a project; `deploy` writes into the project itself. The four parts
are the same, so the mapping lives in `emit` and this module only differs where
writing into somebody else's tree has to be careful:

- it never deletes anything, so a part an adapter no longer declares survives an
  earlier deploy (a limit the README states rather than a rule this module breaks);
- it merges `opencode.json` instead of writing it wholesale: the user's other keys,
  their own `instructions` entries and their other MCP servers stay;
- it refuses a workspace it did not create unless `--force` says to adopt it, and
  reports which of its own files that adoption overwrote;
- the adapter's copy is namespaced under `.opencode/`, because a project may well
  have a directory called `adapter/` of its own.

Nothing here imports hermit: the server is still a string in the JSON.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil

from . import __version__ as CONVERTER_VERSION
from .emit import (AUDIT_DIR, AUDIT_LOG, CONFIG, CONTEXT, DIR, IGNORED, RECORD, SCHEMA,
                   SERVER_COMMAND, Unsupported, agent_file, copy_skills, load, role_body, write_json)

# This converter's record inside a workspace, and the only marker that makes one ours.
# Namespaced: a workspace is the user's, so nothing this tool owns sits at its root.
WORKSPACE_RECORD = f"{DIR}/{RECORD}"
# The adapter's copy, namespaced for the same reason: `adapter/` at a project root is
# a name a project may already be using.
WORKSPACE_ADAPTER = f"{DIR}/adapter"


class WorkspaceError(ValueError):
    """A workspace this tool may not write into, and why."""


def _read_config(path: Path) -> dict:
    """The workspace's own `opencode.json`, which may not be valid JSON at all."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise WorkspaceError(
            f"{CONFIG} is not valid JSON ({exc}), and this tool merges into it rather than replacing it. "
            "Fix the file, or move it aside and deploy again.") from None
    if not isinstance(data, dict):
        raise WorkspaceError(f"{CONFIG} must hold a JSON object, not a {type(data).__name__}")
    return data


def _targets(bundle, roles: dict) -> list:
    """The workspace-relative paths this deploy writes, in a stable order."""
    names = [CONFIG, WORKSPACE_RECORD, WORKSPACE_ADAPTER]
    if bundle.has_context:
        names.append(CONTEXT)
    names.extend(f"{DIR}/agents/{native}.md" for native in roles.values())
    names.extend(f"{DIR}/skills/{skill}" for skill in _skill_names(bundle))
    return names


def _skill_names(bundle) -> list:
    """The skills the adapter declares, without writing anything yet."""
    declared = bundle.manifest.get("skills")
    if not declared:
        return []
    source = (bundle.adapter / declared).resolve()
    if not source.is_dir():
        return []
    return [child.name for child in sorted(source.iterdir()) if (child / "SKILL.md").is_file()]


def _merge(existing: dict, *, instructions: list, server: dict | None, server_name: str) -> dict:
    """The user's configuration with this adapter's parts added, and nothing removed."""
    config = dict(existing)
    config.setdefault("$schema", SCHEMA)
    if instructions:
        declared = config.get("instructions")
        if declared is None:
            config["instructions"] = list(instructions)
        elif not isinstance(declared, list):
            raise WorkspaceError(
                f"{CONFIG}: `instructions` holds a {type(declared).__name__}, not a list, and this tool "
                "appends to it rather than replacing it. Make it a list and deploy again.")
        elif instructions[0] not in declared:
            config["instructions"] = [*declared, instructions[0]]
    if server is not None:
        declared = config.get("mcp")
        if declared is None:
            declared = {}
        elif not isinstance(declared, dict):
            raise WorkspaceError(
                f"{CONFIG}: `mcp` holds a {type(declared).__name__}, not a mapping, and this tool adds "
                "one server to it rather than replacing it. Make it an object and deploy again.")
        config["mcp"] = {**declared, server_name: server}
    return config


def deploy(adapter: Path, workspace: Path, *, allow_lossy: bool = False, force: bool = False) -> dict:
    """Write the adapter's OpenCode parts into `workspace`, in place."""
    bundle = load(adapter)
    if bundle.hooks and not allow_lossy:
        events = ", ".join(bundle.hooks)
        raise Unsupported(f"An OpenCode workspace cannot carry these parts of the {bundle.id} adapter:\n"
                          f"- hooks: no host configuration carries an adapter's lifecycle hooks yet ({events}); "
                          "connect them in a workspace with `hermit deploy --host codex` or `--host claude-code`\n"
                          "Pass --allow-lossy to deploy without them.")
    omitted = ["hooks"] if bundle.hooks else []

    workspace = Path(workspace).resolve()
    if workspace == bundle.adapter or bundle.adapter in workspace.parents or workspace in bundle.adapter.parents:
        raise WorkspaceError("The workspace must be separate from the adapter")

    record_path = workspace / WORKSPACE_RECORD
    previous = json.loads(record_path.read_text()) if record_path.is_file() else {}
    roles = {role["name"]: agent_file(role, role_body(bundle.adapter, role))[0] for role in bundle.roles}

    adopted = []
    if not previous:
        if workspace.exists() and any(workspace.iterdir()) and not force:
            raise WorkspaceError(
                "Refusing to deploy into a nonempty workspace this tool did not create. Pass --force to adopt it: "
                "this writes only the files it generates and leaves everything else alone.")
        adopted = [name for name in _targets(bundle, roles) if (workspace / name).exists()]

    existing = _read_config(workspace / CONFIG)
    server_name = bundle.server
    if server_name in (existing.get("mcp") or {}) and previous.get("server_name") != server_name and not force:
        raise WorkspaceError(
            f"{CONFIG} already declares an MCP server named {server_name} that this tool did not write. "
            "Rename it, or pass --force to replace it.")

    server = None
    if bundle.tools:
        server = {"type": "local",
                  "command": [SERVER_COMMAND, "serve", WORKSPACE_ADAPTER, "--audit-log", f"{AUDIT_DIR}/{AUDIT_LOG}"],
                  "enabled": True}
    instructions = [CONTEXT] if bundle.has_context else []
    config = _merge(existing, instructions=instructions, server=server, server_name=server_name)

    # From here on, files are written. Only ever paths this tool generates: nothing in the
    # workspace is removed, so a part an earlier deploy wrote survives an adapter that no
    # longer declares it. That is a limit stated in the README, not an accident.
    workspace.mkdir(parents=True, exist_ok=True)
    if bundle.has_context:
        text = bundle.context
        for name, native in roles.items():
            text = text.replace(f"`{name}`", f"`{native}`")
        (workspace / CONTEXT).parent.mkdir(parents=True, exist_ok=True)
        (workspace / CONTEXT).write_text(text.strip() + "\n")
    for role in bundle.roles:
        native = roles[role["name"]]
        path = workspace / DIR / "agents" / f"{native}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(agent_file(role, role_body(bundle.adapter, role))[1])
    skills = copy_skills(bundle, workspace / DIR / "skills")
    if bundle.tools:
        (workspace / AUDIT_DIR).mkdir(parents=True, exist_ok=True)
    target = workspace / WORKSPACE_ADAPTER
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()
    shutil.copytree(bundle.adapter, target, ignore=shutil.ignore_patterns(*IGNORED), symlinks=True)
    write_json(workspace / CONFIG, config)

    record = {"adapter": bundle.id, "adapter_version": bundle.version, "layout": bundle.layout,
              "converter": f"hermit-opencode {CONVERTER_VERSION}", "server_name": bundle.server,
              "skills": skills, "roles": roles, "context": CONTEXT if bundle.has_context else None}
    write_json(workspace / WORKSPACE_RECORD, record)
    return {"mode": "deploy", "host": "opencode", "adapter_id": bundle.id, "version": bundle.version,
            "layout": bundle.layout, "workspace": str(workspace), "config": CONFIG,
            "adapter_dir": WORKSPACE_ADAPTER,
            "next": [f"cd {workspace} && opencode"],
            "context": CONTEXT if bundle.has_context else None,
            "skills": skills, "roles": roles,
            "server_name": server_name if bundle.tools else None,
            "tools": [tool["name"] for tool in bundle.tools],
            "adopted": adopted, "omitted": omitted, "record": WORKSPACE_RECORD}
