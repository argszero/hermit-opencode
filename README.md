# hermit-opencode

Convert a [hermit](https://github.com/Infini-AI-Lab/hermit) adapter into an
[OpenCode](https://opencode.ai) configuration.

A hermit adapter is a directory of files: `ADAPTER.md` (the acting agent's
context), `exports.yaml` (skills, subagents, tools), `.hermit/adapter.yaml` (the
template's metadata). OpenCode reads its configuration from the project
directory it is opened in. This tool maps one onto the other, so an adapter's
four parts arrive in OpenCode's own places:

| Adapter part | Where it lands | Why there |
|---|---|---|
| `ADAPTER.md` (context) | `.opencode/context.md`, listed in `opencode.json`'s `instructions` | OpenCode **combines** every instruction file with the project's own `AGENTS.md`, so a project that already has rules keeps them |
| `exports.yaml` → `tools` | `opencode.json`'s `mcp.<server>`: `type: local`, running `hermit serve` | OpenCode starts a local MCP server and speaks stdio to it |
| `exports.yaml` → `skills` | `.opencode/skills/<name>/SKILL.md` | OpenCode discovers skills from that directory |
| `exports.yaml` → `agents` | `.opencode/agents/<name>.md`, frontmatter `mode: subagent` | the file name **is** the agent's name in OpenCode |

The adapter itself is copied to `adapter/` inside the output, so the emitted
configuration is self-contained: copy it to another machine and nothing dangles.

## Install

```bash
pip install git+https://github.com/argszero/hermit-opencode
```

Python 3.11 or later. The only runtime dependency is PyYAML.

**This package does not depend on, import, or install `hermit`.** It reads
adapter files and writes configuration. The `hermit serve adapter` line is a
*string* in the emitted JSON, run later by OpenCode — so install hermit
separately, where OpenCode runs, and only if the adapter declares tools.

### Requirements — which hermit, for which part

Hermit itself is needed only for the **tool server**. Everything else in the
output is plain files that OpenCode reads on its own.

| Part of the output | Needs hermit? | Which hermit |
|---|---|---|
| `.opencode/context.md`, `.opencode/skills/`, `.opencode/agents/`, and `opencode.json`'s `instructions` | No | any — OpenCode reads these directly |
| `opencode.json`'s `mcp.<server>`, the command `hermit serve` runs | **Yes** | a hermit that reads the `.hermit/adapter.yaml` + `exports.yaml` layout: git `main`, or any release **after 0.1.0** |

**Hermit `hermit-harness 0.1.0` from PyPI — the only released version, uploaded
2026-10-26 — cannot serve the embedded adapter.** Its manifest reader wants
`adapter.yaml` at the adapter root, the layout hermit replaced in its own `#41`;
both the embedded copy and the source adapter are the newer layout, so no path,
flag or environment setting makes 0.1.0 serve this output. With 0.1.0 installed,
the emitted `mcp` entry fails to start and OpenCode reports the server as
unavailable; the context, skills and roles still work, because they never touch
hermit.

Measured, both readings in [Verification](#verification--what-was-actually-run)
below. Install hermit with:

```bash
pip install "git+https://github.com/Infini-AI-Lab/hermit"   # reads the .hermit layout
```

## Use

```bash
hermit-opencode path/to/adapter --output out/
```

It prints a JSON report (`adapter_id`, `layout`, `context`, `skills`, `roles`,
`tools`, `server_name`, `omitted`) and writes:

```text
out/
  opencode.json          the configuration
  hermit-opencode.json   which adapter, which layout, which converter
  .opencode/context.md   the adapter's context            (only if it has one)
  .opencode/skills/      one directory per skill          (only if it declares skills)
  .opencode/agents/      one file per subagent            (only if it declares roles)
  adapter/               the whole adapter, embedded
```

Then:

```bash
cp -R out/. /path/to/your/project/
cd /path/to/your/project && opencode
```

**`cwd` is `.` and every path in `opencode.json` is workspace-relative, on
purpose.** OpenCode expands no plugin-root variable, so a configuration that
named this machine's absolute paths would break the moment it was copied
anywhere else. This is the one constraint that shapes the whole output.

The audit log lives at `.opencode/audit/tool-calls.jsonl`, outside `adapter/`,
because a hermit `Session` requires the audit log to sit outside the adapter it
serves.

### Both adapter manifest layouts

Hermit changed its adapter layout in 0.1.0 and this tool reads both:

| Layout | Where the manifest is | `contract` |
|---|---|---|
| Hermit 0.1.0 and later | `.hermit/adapter.yaml` (metadata) beside `exports.yaml` (agents, skills, tools) | `"2"` |
| Hermit 0.1 | one `adapter.yaml` at the adapter root, holding an `exports:` section | `"1"` |

The report's `layout` field says which one was read (`1` or `2`). A directory
with neither file is refused by name rather than half-converted.

### What it refuses

Nothing is silently dropped. An adapter that declares **lifecycle hooks** is
refused, because no host configuration carries them — `hermit deploy --host
codex` or `--host claude-code` connects those in a workspace. An adapter whose
template declares **`plugin-portable: false`** is refused too: its per-task
context is computed by the harness before the agent's first model call, and an
installed configuration has no such moment. Both are refused *before* anything
is written, and `--allow-lossy` converts anyway and lists what was left out
under `omitted`.

Re-running into the same output replaces only what it generated, so an adapter
that loses a skill or a role loses it in the output too — and the tool-call log
OpenCode wrote there is **not** generated, so it survives.

## Verification — what was actually run

Everything below was run on macOS, Python 3.13.9 — items 1–4 against hermit
`f1027bf` and OpenCode's published schema, item 5 against the released PyPI
package and hermit `604ecf0`. Re-runnable from the repository root:

```bash
python -m venv .venv && ./.venv/bin/pip install -e ".[test]"
./.venv/bin/python -m pytest tests/ -v
```

**1. The suite: 12 passed, no network, no hermit installed.**

```text
tests/test_emit.py::test_opencode_carries_every_part PASSED
tests/test_emit.py::test_opencode_without_context_writes_no_instructions PASSED
tests/test_emit.py::test_opencode_keeps_the_audit_log_of_an_earlier_conversion PASSED
tests/test_emit.py::test_reads_the_pre_0_1_layout PASSED
tests/test_emit.py::test_a_directory_that_is_not_an_adapter_is_reported PASSED
tests/test_emit.py::test_refuses_a_foreign_nonempty_directory PASSED
tests/test_emit.py::test_refuses_hooks_but_can_leave_them_out PASSED
tests/test_emit.py::test_refuses_an_adapter_that_is_not_plugin_portable PASSED
tests/test_emit.py::test_cli_emits_and_exits_zero PASSED
tests/test_emit.py::test_cli_reports_a_bad_adapter_with_exit_2 PASSED
tests/test_emit.py::test_emitted_config_validates_against_the_opencode_schema PASSED
tests/test_emit.py::test_the_served_command_and_the_readme_agree_on_which_hermit_can_run_it PASSED
```

The first three are ported from hermit pull request #39 (`f1027bf`), where they
were the specification for `hermit convert --target opencode`; they assert
OpenCode's format, not hermit's internals, so they still hold here. The fourth
and fifth cover the second manifest layout, which that request never had to.

`python -c "import hermit"` in that venv raises `ModuleNotFoundError`. That is
the zero-dependency claim, measured rather than asserted — but run it from this
repository's root or from a neutral directory, **not** from inside a hermit
checkout: there a `hermit/` package directory sits in the current working
directory and Python imports it without anything being installed. Measured both
ways: `ModuleNotFoundError` from `/tmp`, and this package's only declared
requirement is `PyYAML`.

**2. A real conversion**, of hermit's own example adapter
(`docs/_examples/file_adapter`) — `hermit-opencode <adapter> --output out`
wrote exactly the tree shown under [Use](#use), reporting
`"adapter_id": "file-example", "layout": 2, "skills": ["verify-output"],
"roles": {"reviewer": "reviewer"}, "tools": ["count_words"]`.

**3. The emitted `opencode.json` validates against OpenCode's schema.** The
schema is vendored at `tests/assets/opencode-config.schema.json`, fetched with:

```bash
curl -sS -o tests/assets/opencode-config.schema.json https://opencode.ai/config.json
```

(`urllib` gets HTTP 403 from `opencode.ai`; `curl` gets 200. That is why the
fetch is spelled this way and why the schema is committed rather than fetched at
test time.) Validated with `jsonschema.Draft202012Validator` — valid, top-level
keys `['$schema', 'instructions', 'mcp']`.

**4. The command in the emitted `opencode.json` was run.** Started from the
output directory exactly as the config spells it — `hermit serve adapter
--audit-log .opencode/audit/tool-calls.jsonl`, `cwd: "."` — the server answered
a real MCP `initialize` / `tools/list` / `tools/call` exchange:

```text
tools/list -> ['count_words']
tools/call count_words('one two three') -> {'count': 3}
```

and appended to the relative audit path:

```json
{"time": "…", "pid": …, "adapter": "file-example", "version": "1.0", "tool": "count_words",
 "arguments": {"text": "one two three"}, "status": "ok", "result": {"count": 3}}
```

**5. The same command against the hermit a user can actually install — both
readings.** Two clean virtualenvs, the same output directory, the same emitted
`mcp` command run from the output directory with `cwd: "."`. The adapter
converted was hermit's own `docs/_examples/file_adapter` at `604ecf0`.

*Reading A — `pip install hermit-harness==0.1.0` from PyPI. It fails:*

```text
$ hermit serve adapter --audit-log .opencode/audit/tool-calls.jsonl
EXIT CODE: 1
  File ".../hermit/adapter/manifest.py", line 26, in read_manifest
    raise ValueError(f"Missing {MANIFEST} in {root}")
ValueError: Missing adapter.yaml in <output>/adapter
```

*Reading B — hermit from git `main` (measured at `604ecf0`). It works:*

```text
$ hermit serve adapter --audit-log .opencode/audit/tool-calls.jsonl
{"jsonrpc":"2.0","id":1,"result":{"capabilities":{...},"protocolVersion":"2024-11-05",
 "serverInfo":{"name":"file-example","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"count_words", ...}]}}
EXIT CODE: 0
```

The difference is the manifest layout, not this converter: 0.1.0's reader looks
for `adapter.yaml` at the adapter root, and the embedded adapter is the layout
hermit moved to in its own `#41`. That is why the [Requirements](#requirements--which-hermit-for-which-part)
table names a minimum, and why this repository's test suite pins the emitted
command and that table to each other.

`git+https://github.com/Infini-AI-Lab/hermit` was the intended spelling of
reading B and its first attempt died at `fatal: unable to access …: Recv
failure: Connection reset by peer`, so the same commit (`604ecf0`) was installed
from a local clone of that repository. The code measured is that commit's,
fetched over git; the route to it was local rather than the network.

### What was NOT verified

**No live OpenCode session has ever loaded this output.** There were no OpenCode
credentials or model backend available while this was built, so the end-to-end
path stops at the MCP server: the configuration is schema-valid and its server
command works, but "OpenCode actually started, read `.opencode/`, and used the
skill and subagent" is **unproven**. A schema-valid configuration is not a loaded
one. If you run it and something is wrong, that is exactly the report this
repository wants.

Also unverified, for the same reason: whether OpenCode's tool-name handling
rewrites `file_example` into its own naming scheme, and how it renders a
`description` containing non-ASCII text (it is emitted as a JSON string inside
YAML frontmatter, which is valid but worth eyeballing in a live session).

## Relation to hermit's own OpenCode work

Hermit's issue
[#35](https://github.com/Infini-AI-Lab/hermit/issues/35) asks for OpenCode as an
additional backend, in two halves: running tasks against an adapter
(`convert`), and deploying a trained adapter into a workspace (`deploy`). This
package is the first half, as a standalone tool.

Hermit cannot host this itself: `hermit/plugins/__init__.py` is a hardcoded map
of four emitters with no entry points or registration hook, so a fifth host
cannot be added without changing hermit's core. A converter for a host hermit
does not yet support therefore has to ship its own command — which is what this
is.

The code descends from pull request #39, which was closed without being merged;
see `NOTICE` for what was derived and what changed.

The second half — writing into a *workspace* rather than emitting a
configuration — is not implemented here. Hermit pull request #42 proposes it;
this package does not duplicate it.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
