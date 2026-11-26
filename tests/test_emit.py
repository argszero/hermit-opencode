"""The emitted configuration, its refusals, and both adapter layouts.

The four `test_opencode_*` cases are ported unchanged in behaviour from Hermit
pull request #39 (commit f1027bf), where they were the specification for
`hermit convert --target opencode`. They are assertions about OpenCode's format,
not about Hermit's internals, so they still hold here.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from hermit_opencode import SERVER_COMMAND, AdapterError, Unsupported, build, deploy

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests" / "assets" / "file_adapter"          # `contract: "2"`, `.hermit/adapter.yaml`
V1 = ROOT / "tests" / "assets" / "file_adapter_v1"            # Hermit 0.1 layout, `contract: "1"`


def variant(tmp_path, *, roles=True, context=True):
    """A copy of the example adapter, optionally without its role or with an empty context."""
    a = tmp_path / "adapter"
    shutil.copytree(EXAMPLE, a)
    if not roles:
        exports = yaml.safe_load((a / "exports.yaml").read_text())
        del exports["agents"]
        (a / "exports.yaml").write_text(yaml.safe_dump(exports, sort_keys=False))
        shutil.rmtree(a / "agents")
    if not context:
        (a / "ADAPTER.md").write_text("")
    return a


def test_opencode_carries_every_part(tmp_path):
    out = tmp_path / "opencode"
    result = build(EXAMPLE, out)
    config = json.loads((out / "opencode.json").read_text())
    assert config["$schema"] == "https://opencode.ai/config.json"
    # Context: a file listed in `instructions`, which OpenCode combines with the project's own AGENTS.md.
    assert config["instructions"] == [".opencode/context.md"]
    context = (out / ".opencode" / "context.md").read_text()
    assert context.startswith("This adapter's files are in `adapter/`.")
    assert "Review the task requirements before acting. Check the result before returning it." in context
    # Tools: a local MCP server run from the workspace, so the config names no path from this machine.
    server = config["mcp"]["file_example"]
    assert server["type"] == "local" and server["enabled"] is True
    # No `cwd`: opencode 1.1.2 rejects the key and refuses the configuration with it.
    assert set(server) == {"type", "command", "enabled"}
    assert server["command"] == ["hermit", "serve", "adapter", "--audit-log", ".opencode/audit/tool-calls.jsonl"]
    assert str(out) not in json.dumps(config)
    # Roles: the file name is the agent's name, and the frontmatter makes it a subagent.
    agent = (out / ".opencode" / "agents" / "reviewer.md").read_text()
    assert agent.startswith('---\ndescription: "Check a result against the task requirements."\nmode: subagent\n---\n')
    assert agent.rstrip().endswith("Explain any mismatch.")
    assert "\nname:" not in agent
    assert (out / ".opencode" / "skills" / "verify-output" / "SKILL.md").is_file()
    # The embedded adapter keeps the manifest where the framework now keeps it.
    assert (out / "adapter" / ".hermit" / "adapter.yaml").is_file() and (out / "adapter" / "exports.yaml").is_file()
    assert result["roles"] == {"reviewer": "reviewer"} and result["omitted"] == []
    assert result["plugin"] == str(out) and result["context"] == ".opencode/context.md"
    assert result["layout"] == 2 and result["tools"] == ["count_words"]
    # The record names this converter, never a hermit version: `hermit serve` compares the
    # `framework` key of its own record, and this file has none.
    record = json.loads((out / "hermit-opencode.json").read_text())
    assert record["adapter"] == "file-example" and record["adapter_version"] == "1.0"
    assert "framework" not in record and record["converter"].startswith("hermit-opencode ")


def test_opencode_without_context_writes_no_instructions(tmp_path):
    out = tmp_path / "opencode"
    result = build(variant(tmp_path, context=False), out)
    assert "instructions" not in json.loads((out / "opencode.json").read_text())
    assert result["context"] is None and not (out / ".opencode" / "context.md").exists()


def test_opencode_keeps_the_audit_log_of_an_earlier_conversion(tmp_path):
    """Re-converting replaces the generated entries; the tool-call log OpenCode wrote is not one of them."""
    out = tmp_path / "opencode"
    build(EXAMPLE, out)
    log = out / ".opencode" / "audit" / "tool-calls.jsonl"
    log.write_text('{"tool": "count_words"}\n')
    shutil.rmtree(tmp_path / "adapter", ignore_errors=True)
    result = build(variant(tmp_path, roles=False, context=False), out)
    assert log.read_text() == '{"tool": "count_words"}\n'
    assert result["roles"] == {} and not (out / ".opencode" / "agents").exists()
    assert not (out / ".opencode" / "context.md").exists()


def test_reads_the_pre_0_1_layout(tmp_path):
    """Hermit 0.1 kept the exports inside adapter.yaml at the adapter's root."""
    out = tmp_path / "v1"
    result = build(V1, out)
    assert result["layout"] == 1 and result["adapter_id"] == "file-example"
    config = json.loads((out / "opencode.json").read_text())
    assert config["instructions"] == [".opencode/context.md"]
    assert config["mcp"]["file_example"]["command"][:3] == ["hermit", "serve", "adapter"]
    assert (out / ".opencode" / "agents" / "reviewer.md").is_file()
    assert (out / "adapter" / "adapter.yaml").is_file()


def test_a_directory_that_is_not_an_adapter_is_reported(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AdapterError, match="is not an adapter"):
        build(empty, tmp_path / "out")


def test_refuses_a_foreign_nonempty_directory(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "someone-elses-file").write_text("x")
    with pytest.raises(ValueError, match="did not create"):
        build(EXAMPLE, out)
    assert (out / "someone-elses-file").read_text() == "x"


def test_refuses_hooks_but_can_leave_them_out(tmp_path):
    """No host configuration carries an adapter's lifecycle hooks: refuse, or say they were left out."""
    a = variant(tmp_path, roles=False, context=False)
    (a / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "true"}]}]}}))
    (a / "exports.yaml").write_text((a / "exports.yaml").read_text() + "hooks: hooks.json\n")
    with pytest.raises(Unsupported, match=r"- hooks: no host configuration carries"):
        build(a, tmp_path / "x")
    assert not (tmp_path / "x").exists()
    assert build(a, tmp_path / "y", allow_lossy=True)["omitted"] == ["hooks"]


def test_refuses_an_adapter_that_is_not_plugin_portable(tmp_path):
    a = variant(tmp_path, roles=False, context=False)
    meta = yaml.safe_load((a / ".hermit" / "adapter.yaml").read_text())
    meta["plugin-portable"] = False
    (a / ".hermit" / "adapter.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    with pytest.raises(Unsupported, match="plugin-portable: false"):
        build(a, tmp_path / "out")


def test_names_the_files_no_export_connects(tmp_path):
    """Parity with hermit `42fbd08`, measured from this tool's own emission.

    The reach is knowable: the context, the manifest `hermit serve` reads, the skill and
    role directories, and each tool's entrypoint are all connected, so none of them is
    named. `.hermit/EVOLVER.md` (the evolution prompt) and `README.md` are carried into
    `adapter/` and reached by nothing — which is the thing the user cannot see otherwise.
    """
    out = tmp_path / "connects"
    result = build(EXAMPLE, out)
    assert result["unnamed_files"] == [".hermit/EVOLVER.md", "README.md"]
    copied = sorted(p.relative_to(out / "adapter").as_posix()
                    for p in (out / "adapter").rglob("*") if p.is_file())
    assert set(result["unnamed_files"]) <= set(copied), "every file it names is in the copy it describes"
    for name in ("ADAPTER.md", "exports.yaml", ".hermit/adapter.yaml",
                 "skills/verify-output/SKILL.md", "agents/reviewer.md", "tools.py"):
        assert name in copied and name not in result["unnamed_files"], f"{name} is reached by the configuration"


def test_unnamed_files_leaves_out_what_is_not_carried_or_is_the_harnesss(tmp_path):
    """Three things stay out of the list, each for its own reason, and each is checkable."""
    a = variant(tmp_path)
    (a / "data").mkdir()
    (a / "data" / "notes.txt").write_text("carried, and named by nothing\n")
    (a / "AGENTS.md").write_text((a / "ADAPTER.md").read_text())     # a copy of the context
    (a / ".hermit" / "memory").mkdir()
    (a / ".hermit" / "memory" / "bank.json").write_text("{}\n")
    (a / "exports.yaml").write_text((a / "exports.yaml").read_text() + "internal:\n  - .hermit/memory/**\n")
    (a / "__pycache__").mkdir()
    (a / "__pycache__" / "tools.cpython-313.pyc").write_bytes(b"\x00")
    result = build(a, tmp_path / "leaves_out")
    assert "data/notes.txt" in result["unnamed_files"]
    assert "AGENTS.md" not in result["unnamed_files"], "a copy of the context is already carried as the context"
    assert ".hermit/memory/bank.json" not in result["unnamed_files"], "the harness reads it; it is not the session's"
    assert not any(name.endswith(".pyc") for name in result["unnamed_files"]), (
        "a file the copy leaves out cannot be reported as carried-but-unnamed")


def test_the_context_names_the_files_no_export_connects(tmp_path):
    """The session is told, in the file it reads, about the files no export reaches.

    `unnamed_files` in the report is read by whoever runs the conversion; the context is
    what the session reads when it starts, so a file named only in the report is a file
    nothing that acts has been told about. hermit's own deployment builds this text from
    three parts in one order — the folder note, the adapter's context, then the files it
    does not connect (`hermit/hosts/opencode.py`, over `hermit.hosts.inputs`) — and this
    case holds this tool to that composition.
    """
    out = tmp_path / "named"
    result = build(EXAMPLE, out)
    context = (out / ".opencode" / "context.md").read_text()
    parts = context.split("\n\n")
    assert len(parts) == 3, f"the context is not the three parts hermit composes: {context!r}"
    note, adapter_text, others = parts
    assert note.startswith("This adapter's files are in `adapter/`.")
    assert adapter_text == "Review the task requirements before acting. Check the result before returning it."
    assert others.startswith("Other files of this adapter (read one when it is relevant):")
    # Each carried file the configuration does not reach, under the folder it was copied to,
    # with the line its own author wrote for a reader rather than its first line of code.
    assert "- `adapter/.hermit/EVOLVER.md`: Editable files" in others
    assert "- `adapter/README.md`: File interface example" in others
    for name in result["unnamed_files"]:
        assert f"- `adapter/{name}`" in others, f"{name} is not named in the context the session reads"
    for reached in ("ADAPTER.md", "exports.yaml", "tools.py", "agents/reviewer.md"):
        assert f"`adapter/{reached}`" not in others, f"{reached} is reached, so the list may not name it"


def test_the_context_lists_sixty_files_and_counts_the_rest(tmp_path):
    """An adapter carrying more than the list holds gets a bounded section, not a wall.

    The cap keeps a large adapter's context readable; the count is what keeps a bounded
    list honest about what it left out.
    """
    a = variant(tmp_path, roles=False)
    (a / "data").mkdir()
    for n in range(65):
        (a / "data" / f"note-{n:02d}.txt").write_text(f"note {n}\n")
    out = tmp_path / "bounded"
    result = build(a, out)
    context = (out / ".opencode" / "context.md").read_text()
    listed = [line for line in context.splitlines() if line.startswith("- `adapter/")]
    assert len(result["unnamed_files"]) == 67 and len(listed) == 60
    assert "- and 7 more files under `adapter/`" in context
    assert "- `adapter/data/note-64.txt`" not in context, "the list stops at the cap, and says so"


def test_cli_emits_and_exits_zero(tmp_path):
    out = tmp_path / "cli"
    proc = subprocess.run([sys.executable, "-m", "hermit_opencode.cli", str(EXAMPLE), "--output", str(out)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["adapter_id"] == "file-example"
    assert (out / "opencode.json").is_file()


def test_cli_reports_a_bad_adapter_with_exit_2(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = subprocess.run([sys.executable, "-m", "hermit_opencode.cli", str(empty), "--output", str(tmp_path / "o")],
                          capture_output=True, text=True)
    assert proc.returncode == 2 and "is not an adapter" in proc.stderr


def test_emitted_config_validates_against_the_opencode_schema(tmp_path):
    """Against the schema this repository ships, fetched from opencode.ai with the command in the README."""
    schema_path = ROOT / "tests" / "assets" / "opencode-config.schema.json"
    if not schema_path.is_file():
        pytest.skip("the OpenCode schema has not been fetched; see the README")
    jsonschema = pytest.importorskip("jsonschema")
    out = tmp_path / "validated"
    build(EXAMPLE, out)
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads((out / "opencode.json").read_text()))


def test_the_served_command_and_the_readme_agree_on_which_hermit_can_run_it(tmp_path):
    """The emitted `mcp` command and the README's Requirements table name the same minimum.

    The gap this pins is silent in this repository and loud only in a user's
    OpenCode session: hermit `hermit-harness 0.1.0` from PyPI reads `adapter.yaml`
    at the adapter root, so it cannot open the embedded copy, and the emitted
    server fails to start; `hermit-harness 0.2.0` reads `.hermit/adapter.yaml`
    and serves it. Both measured in the README's Verification section. If a later
    edit changes the served command or relaxes the requirement, one of these
    assertions fails instead of the user finding out.
    """
    out = tmp_path / "pinned"
    build(EXAMPLE, out)
    config = json.loads((out / "opencode.json").read_text())
    (command,) = [entry["command"] for entry in config["mcp"].values()]
    assert command[:2] == [SERVER_COMMAND, "serve"]

    readme = (ROOT / "README.md").read_text()
    requirements = readme.split("### Requirements", 1)[1].split("\n## ", 1)[0]
    assert " ".join(command[:2]) in readme, "the README must name the command it tells the user to install hermit for"
    assert ".hermit/adapter.yaml" in requirements, "the Requirements table must name the layout a hermit needs"
    assert "hermit-harness 0.1.0" in requirements, "the Requirements table must name the release that cannot serve it"
    assert "0.2.0" in requirements, "the Requirements table must name the release that can serve it"
    assert "git+https://github.com/Infini-AI-Lab/hermit" not in requirements, (
        "installing hermit from git is no longer needed: `hermit-harness 0.2.0` reads the embedded layout"
    )


def test_the_workspace_command_and_the_readme_agree_on_what_deploy_writes(tmp_path):
    """`deploy`'s emitted entry, and the README's account of it, name the same paths.

    The failure this pins is a deployment whose server command points somewhere the
    README does not describe — silent in this repository, and loud only in a user's
    workspace. It also pins the limits: they are what a reader decides on, so a later
    edit may not quietly drop them.
    """
    workspace = tmp_path / "ws"
    result = deploy(EXAMPLE, workspace)
    config = json.loads((workspace / "opencode.json").read_text())
    (command,) = [entry["command"] for entry in config["mcp"].values()]
    assert command[:2] == [SERVER_COMMAND, "serve"]
    assert command[2] == ".opencode/adapter"
    assert set(config["mcp"][result["server_name"]]) == {"type", "command", "enabled"}

    readme = (ROOT / "README.md").read_text()
    deployed = readme.split("## Deploy into a workspace", 1)[1].split("\n## ", 1)[0]
    assert "hermit-opencode deploy" in deployed, "the README must name the deploy command"
    assert ".opencode/adapter/" in deployed, "the README must name where deploy puts the adapter copy"
    assert "--force" in deployed, "the README must say how to adopt a project you already have"
    assert "It never deletes anything." in deployed, "the README must state that deploy never deletes"
    assert "under version control" in deployed, "the README must tell the reader to deploy somewhere undoable"
    # The load check is what the remaining caveat rests on, and it is pinned too.
    caution = readme.split("### What was NOT verified", 1)[1]
    assert "1.1.2" in caution, "the note must name the OpenCode version the load check ran on"
    assert "opencode agent list" in caution, "the note must name the command that showed discovery"
    assert "writes into a project you already have" in caution, (
        "deploy writes into a user's real project: the remaining note must say so"
    )


def test_the_output_is_something_opencode_actually_loads(tmp_path):
    """The `mcp` entry carries only keys `opencode 1.1.2` accepts, and the README says so.

    Measured 2026-11-07 against `opencode 1.1.2`. `opencode agent list` in a deployed
    workspace exited 1 — `Configuration is invalid … Invalid input mcp.file_example` — and
    `--print-logs --log-level DEBUG` named the cause: `Unrecognized key: "cwd"`. The schema
    opencode.ai publishes still documents `cwd`, and the copy committed under `tests/assets/`
    validates a configuration carrying it, so a schema check cannot stand in for a load
    check. 0.2.0 shipped that key and no OpenCode would start with it.

    The failure this pins is silent in this repository and loud in a user's project. Two
    assertions: the emitted entry may carry only keys the runtime's validator knows, and the
    README may not drift back to claiming no session has ever loaded the output.
    """
    out = tmp_path / "loaded"
    build(EXAMPLE, out)
    config = json.loads((out / "opencode.json").read_text())
    known = {"type", "command", "enabled", "environment", "timeout"}
    for name, entry in config["mcp"].items():
        unknown = set(entry) - known
        assert not unknown, f"`{name}` carries keys opencode 1.1.2 rejects: {sorted(unknown)}"

    readme = (ROOT / "README.md").read_text()
    assert "No live OpenCode session has ever loaded this output" not in readme, (
        "opencode 1.1.2 loads this output: that blanket caveat is no longer true")
    loaded = readme.split("### What was NOT verified", 1)[1]
    assert "1.1.2" in loaded and "opencode agent list" in loaded
