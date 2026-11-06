"""Deploy into a workspace: the four paths, the merge, and what it refuses.

`convert` writes into a directory of its own; this is the other half, where the
tree belongs to somebody else. So the cases that matter here are the ones a fresh
output directory never has: a project that already exists, a second run, and an
`opencode.json` that already holds the user's own keys.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from hermit_opencode import Unsupported, WorkspaceError, deploy

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "tests" / "assets" / "file_adapter"
RECORD = ".opencode/hermit-opencode.json"


def generated(workspace):
    """Every file this tool writes, as bytes, so "did it change" is measurable."""
    out = {}
    for name in ("opencode.json", ".opencode/context.md", ".opencode/agents/reviewer.md",
                 ".opencode/skills/verify-output/SKILL.md", ".opencode/adapter/exports.yaml"):
        path = workspace / name
        assert path.is_file(), f"{name} was not written"
        out[name] = path.read_bytes()
    return out


def test_deploy_writes_the_four_parts_in_place(tmp_path):
    workspace = tmp_path / "project"
    result = deploy(EXAMPLE, workspace)
    config = json.loads((workspace / "opencode.json").read_text())
    # Context: the file, listed in `instructions`, so the project's own AGENTS.md survives.
    assert config["instructions"] == [".opencode/context.md"]
    assert (workspace / ".opencode" / "context.md").is_file()
    assert not (workspace / "AGENTS.md").exists(), "deploy must never write the project's own AGENTS.md"
    # Tools: run from the workspace, naming the adapter this deploy copied in.
    server = config["mcp"]["file_example"]
    assert server["type"] == "local" and "cwd" not in server, (
        "opencode 1.1.2 rejects a `cwd` key and refuses the whole configuration with it")
    assert server["command"] == ["hermit", "serve", ".opencode/adapter",
                                "--audit-log", ".opencode/audit/tool-calls.jsonl"]
    assert str(workspace) not in json.dumps(config), "no absolute path: the workspace must stay copyable"
    # Roles and skills, in OpenCode's own places.
    agent = (workspace / ".opencode" / "agents" / "reviewer.md").read_text()
    assert agent.startswith('---\ndescription: "Check a result against the task requirements."\nmode: subagent\n---\n')
    assert (workspace / ".opencode" / "skills" / "verify-output" / "SKILL.md").is_file()
    # The adapter's copy is namespaced, so a project's own `adapter/` directory is never touched.
    assert (workspace / ".opencode" / "adapter" / ".hermit" / "adapter.yaml").is_file()
    assert not (workspace / "adapter").exists()
    assert result["mode"] == "deploy" and result["roles"] == {"reviewer": "reviewer"}
    assert result["server_name"] == "file_example" and result["omitted"] == []
    assert result["record"] == RECORD and json.loads((workspace / RECORD).read_text())["adapter"] == "file-example"


def test_a_workspace_this_tool_did_not_create_is_refused(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('mine')\n")
    with pytest.raises(WorkspaceError, match="did not create"):
        deploy(EXAMPLE, workspace)
    # Refused before writing anything: the project is exactly as it was.
    assert (workspace / "main.py").read_text() == "print('mine')\n"
    assert sorted(p.name for p in workspace.iterdir()) == ["main.py"]


def test_force_adopts_a_project_and_says_what_it_overwrote(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('mine')\n")
    (workspace / "opencode.json").write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "theme": "tokyonight",
        "instructions": ["docs/rules.md"],
        "mcp": {"other_server": {"type": "local", "command": ["other"], "enabled": True}},
    }))
    result = deploy(EXAMPLE, workspace, force=True)
    # The user's configuration keeps everything that is theirs...
    config = json.loads((workspace / "opencode.json").read_text())
    assert config["theme"] == "tokyonight"
    assert config["instructions"] == ["docs/rules.md", ".opencode/context.md"]
    assert config["mcp"]["other_server"]["command"] == ["other"]
    assert config["mcp"]["file_example"]["enabled"] is True
    # ...and their own files are untouched.
    assert (workspace / "main.py").read_text() == "print('mine')\n"
    # The report names exactly what was already there, so an adoption is never silent.
    assert result["adopted"] == ["opencode.json"]


def test_a_second_deploy_changes_nothing_it_generated(tmp_path):
    """Re-running rewrites the generated files with the same bytes and leaves the rest alone."""
    workspace = tmp_path / "project"
    deploy(EXAMPLE, workspace)
    first = generated(workspace)
    (workspace / "main.py").write_text("print('mine')\n")
    (workspace / ".opencode" / "skills" / "mine" / "SKILL.md").parent.mkdir(parents=True)
    (workspace / ".opencode" / "skills" / "mine" / "SKILL.md").write_text("---\nname: mine\n---\n\nKeep me.\n")
    log = workspace / ".opencode" / "audit" / "tool-calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"tool": "count_words"}\n')

    deploy(EXAMPLE, workspace)
    assert generated(workspace) == first, "a second deploy must be byte-identical"
    # Nothing of the user's is removed: not their files, not their own skill, not the audit log.
    assert (workspace / "main.py").read_text() == "print('mine')\n"
    assert "Keep me." in (workspace / ".opencode" / "skills" / "mine" / "SKILL.md").read_text()
    assert log.read_text() == '{"tool": "count_words"}\n'


def test_deploy_refuses_a_config_it_cannot_merge_into(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "opencode.json").write_text('{"mcp": "not an object"}')
    with pytest.raises(WorkspaceError, match="not a mapping"):
        deploy(EXAMPLE, workspace, force=True)
    assert (workspace / "opencode.json").read_text() == '{"mcp": "not an object"}', "leave it as it was"


def test_deploy_refuses_an_opencode_json_that_is_not_json(tmp_path):
    """It is merged into, never replaced: a file this tool cannot read is a stop, not an overwrite."""
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "opencode.json").write_text('{ "mcp": { /* a comment */ } }')
    with pytest.raises(WorkspaceError, match="not valid JSON"):
        deploy(EXAMPLE, workspace, force=True)
    assert "/* a comment */" in (workspace / "opencode.json").read_text()


def test_deploy_refuses_hooks_before_writing(tmp_path):
    adapter = tmp_path / "adapter"
    import shutil
    shutil.copytree(EXAMPLE, adapter)
    (adapter / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash"}]}}))
    (adapter / "exports.yaml").write_text((adapter / "exports.yaml").read_text() + "hooks: hooks.json\n")
    workspace = tmp_path / "project"
    with pytest.raises(Unsupported, match=r"- hooks: no host configuration carries"):
        deploy(adapter, workspace)
    assert not workspace.exists(), "a refusal writes nothing at all"
    assert deploy(adapter, tmp_path / "w2", allow_lossy=True)["omitted"] == ["hooks"]


def test_deploy_refuses_an_adapter_that_is_not_plugin_portable(tmp_path):
    from hermit_opencode import Unsupported as Refusal
    adapter = tmp_path / "adapter"
    import shutil
    shutil.copytree(EXAMPLE, adapter)
    meta = yaml.safe_load((adapter / ".hermit" / "adapter.yaml").read_text())
    meta["plugin-portable"] = False
    (adapter / ".hermit" / "adapter.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    with pytest.raises(Refusal, match="plugin-portable: false"):
        deploy(adapter, tmp_path / "project")


def test_deploy_refuses_a_workspace_inside_the_adapter(tmp_path):
    with pytest.raises(WorkspaceError, match="separate from the adapter"):
        deploy(EXAMPLE, EXAMPLE / "workspace")


def test_cli_deploys_and_the_old_positional_spelling_still_converts(tmp_path):
    workspace = tmp_path / "project"
    proc = subprocess.run([sys.executable, "-m", "hermit_opencode.cli", "deploy", str(EXAMPLE),
                           "--workspace", str(workspace)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["mode"] == "deploy"
    assert (workspace / "opencode.json").is_file()

    # 0.1.x's documented command, `hermit-opencode <adapter> --output <dir>`, still means convert.
    out = tmp_path / "converted"
    old = subprocess.run([sys.executable, "-m", "hermit_opencode.cli", str(EXAMPLE), "--output", str(out)],
                         capture_output=True, text=True)
    assert old.returncode == 0, old.stderr
    assert json.loads(old.stdout)["target"] == "opencode"
    assert (out / "adapter" / "exports.yaml").is_file()


def test_cli_reports_a_refused_workspace_with_exit_2(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "main.py").write_text("x")
    proc = subprocess.run([sys.executable, "-m", "hermit_opencode.cli", "deploy", str(EXAMPLE),
                           "--workspace", str(workspace)], capture_output=True, text=True)
    assert proc.returncode == 2 and "did not create" in proc.stderr


def test_the_deployed_config_validates_against_the_opencode_schema(tmp_path):
    schema_path = ROOT / "tests" / "assets" / "opencode-config.schema.json"
    if not schema_path.is_file():
        pytest.skip("the OpenCode schema has not been fetched; see the README")
    jsonschema = pytest.importorskip("jsonschema")
    workspace = tmp_path / "project"
    deploy(EXAMPLE, workspace)
    schema = json.loads(schema_path.read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads((workspace / "opencode.json").read_text()))
