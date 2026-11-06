# hermit-opencode

Bring a [hermit](https://github.com/Infini-AI-Lab/hermit) adapter to
[OpenCode](https://opencode.ai): `convert` writes an OpenCode configuration into
a directory of its own, `deploy` writes it into a project you already have.

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

The adapter itself is copied in with the output, so the emitted configuration is
self-contained: copy it to another machine and nothing dangles. `convert` puts
that copy at `adapter/` in its own output directory; [`deploy`](#deploy-into-a-workspace)
puts it at `.opencode/adapter/` inside your project, where a directory named
`adapter/` may already be yours.

## Install

Install the wheel attached to the [latest
release](https://github.com/argszero/hermit-opencode/releases):

```bash
pip install https://github.com/argszero/hermit-opencode/releases/download/0.2.0/hermit_opencode-0.2.0-py3-none-any.whl
```

This is the path to prefer: one HTTP download, no `git` binary, no git endpoint
and no credential involved. It is verified in
[Verification](#verification--what-was-actually-run) item 6 by installing from
that exact URL into an empty virtualenv.

From the repository, if you would rather track `main` — this needs `git` and a
working connection to `github.com`, which is the failure this release exists to
avoid:

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
| `opencode.json`'s `mcp.<server>`, the command `hermit serve` runs | **Yes** | a hermit that reads the `.hermit/adapter.yaml` + `exports.yaml` layout: **`hermit-harness` 0.2.0 or later**, from PyPI |

**`hermit-harness 0.1.0` from PyPI cannot serve the embedded adapter, and 0.2.0
is the release that changed that.** Upstream's
[changelog](https://github.com/Infini-AI-Lab/hermit/blob/main/CHANGELOG.md) dates
0.2.0 to 2026-11-04 and lists the adapter layout as a **breaking** change: the
metadata moved into `.hermit/`, the exports moved into `exports.yaml` at the
adapter root, and "Hermit no longer loads an adapter in the 0.1 layout
(`adapter.yaml` at the root)". Both the embedded copy and the source adapter are
the new layout, so no path, flag or environment setting makes 0.1.0 serve this
output: with 0.1.0 installed the emitted `mcp` entry fails to start and OpenCode
reports the server as unavailable. The context, skills and roles still work under
0.1.0, because they never touch hermit.

Both readings are measured in [Verification](#verification--what-was-actually-run)
below. Install hermit with:

```bash
pip install "hermit-harness>=0.2.0"
```

Until 0.2.0 was published on 2026-11-04, the only hermit that could serve this
output was git `main`, and earlier versions of this page said so. That advice is
withdrawn: the release says the same thing, and it needs no `git` binary.

**Check which hermit you have.** `pip show hermit-harness` now separates the two
releases (`0.2.0` vs `0.1.0`), but the manifest reader is the mechanical check
behind it, and it is the one that also covers a git checkout between the two
releases, which still reports `Version: 0.1.0`:

```bash
python -c "from hermit.adapter import manifest; print(manifest.MANIFEST)"
```

`.hermit/adapter.yaml` → this output's tool server will start. `adapter.yaml` →
you have `0.1.0`, and the `mcp` entry will fail with `Missing adapter.yaml in
<output>/adapter`.

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

Hermit changed its adapter layout on the way to 0.2.0, and this tool reads both:

| Layout | Where the manifest is | `contract` |
|---|---|---|
| 0.2.0 and later (and git `main` since hermit `#41`) | `.hermit/adapter.yaml` (metadata) beside `exports.yaml` (agents, skills, tools) | `"2"` |
| 0.1 — the PyPI `0.1.0` release | one `adapter.yaml` at the adapter root, holding an `exports:` section | `"1"` |

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

## Deploy into a workspace

`convert` writes a configuration you then copy into a project. `deploy` writes it
into the project itself, in one step:

```bash
hermit-opencode deploy path/to/adapter --workspace /path/to/your/project
```

**Run it first in a fresh directory, or in a tree under version control.** It
writes into a project that is not its own, so the first run in anything you care
about should be one you can undo with `git checkout`. This is the one place where
a mistake costs files rather than an afternoon.

It writes the same four parts — `.opencode/context.md` and its `instructions`
entry, `.opencode/skills/`, `.opencode/agents/`, and `opencode.json`'s `mcp`
entry — plus `.opencode/adapter/` (its copy of the adapter) and
`.opencode/hermit-opencode.json` (its record, and the marker that makes the
workspace its own). Then `cd` there and run `opencode`.

**It merges `opencode.json`; it never replaces it.** Your other keys, your own
`instructions` entries and your other MCP servers stay, and its own entry is
added or updated in place. A second `deploy` of the same adapter changes nothing
it generated, and still leaves everything of yours alone — the audit log at
`.opencode/audit/tool-calls.jsonl` included.

**It refuses a workspace it did not create**, because almost every mistake here
is writing into somebody's project by surprise:

```text
error: Refusing to deploy into a nonempty workspace this tool did not create. Pass
--force to adopt it: this writes only the files it generates and leaves everything
else alone.
```

`--force` is the way to adopt a project you already have, and it reports what it
overwrote, so an adoption is never silent:

```json
"adopted": ["opencode.json"]
```

Two refusals hold even with `--force`, because merging is the only thing this tool
does to your files and both mean it cannot merge: an `opencode.json` that is not
valid JSON, and one whose `instructions` or `mcp` key holds the wrong type. It
stops and says which, rather than overwriting a file it could not read.

### What deploy does not do

Named here rather than half-built. Each is a feature of hermit's own `deploy`, and
none of them is implied by the four parts above:

- **It never deletes anything.** A role or skill an earlier deploy wrote, and the
  adapter no longer declares, stays where it is. Remove it yourself.
- **No managed block in `AGENTS.md`.** The context travels as `.opencode/context.md`
  through `instructions`, which OpenCode combines with your `AGENTS.md` — so your
  file is never edited and never needs merging.
- **No lifecycle `hooks`** — refused, as `convert` refuses them, unless you pass
  `--allow-lossy`, in which case they are listed under `omitted`.
- **No container isolation and no per-task `context_tool`** — those belong to
  hermit's session machinery, not to a host configuration.

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

**5. The same command against the hermit a user can actually install — three
readings.** Three clean virtualenvs, the same output directory, the same emitted
`mcp` command run from the output directory with `cwd: "."`. The adapter
converted was hermit's own `docs/_examples/file_adapter`.

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

*Reading C — `pip install hermit-harness==0.2.0` from PyPI, the release of
2026-11-04. It works, and this is the reading the Requirements table names:*

```text
$ hermit serve adapter --audit-log .opencode/audit/tool-calls.jsonl
{"jsonrpc":"2.0","id":1,"result":{"capabilities":{"experimental":{},"tools":{"listChanged":false}},
 "protocolVersion":"2024-11-05","serverInfo":{"name":"file-example","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"description":"Count whitespace-separated words in text.",
 ...,"name":"count_words", ...}]}}
EXIT CODE: 0
$ cat .opencode/audit/tool-calls.jsonl
{"time": "2026-11-05T18:40:08.988714+00:00", "adapter": "file-example", "version": "1.0",
 "tool": "count_words", "arguments": {"text": "one two three"}, "status": "ok", "result": {"count": 3}}
```

The difference is the manifest layout, not this converter: 0.1.0's reader looks
for `adapter.yaml` at the adapter root, and the embedded adapter is the layout
hermit moved to in its own `#41` — the change it then released, as breaking, in
0.2.0. That is why the [Requirements](#requirements--which-hermit-for-which-part)
table names a minimum, and why this repository's test suite pins the emitted
command and that table to each other.

Reading B is kept as the record of how the requirement was established while
0.2.0 did not exist yet: `git+https://github.com/Infini-AI-Lab/hermit` was its
intended spelling and the first attempt died at `fatal: unable to access …: Recv
failure: Connection reset by peer`, so commit `604ecf0` was installed from a
local clone. Reading C is the one to act on, and it needs neither `git` nor a
checkout.

**One caveat on how these were measured.** This machine exports a global
`PYTHONPATH`, and an earlier pass at readings A and B silently imported hermit's
own declared dependencies (PyYAML, `typing_extensions`) from that variable
instead of from the virtualenv. Reading C was re-measured with the variable
cleared and every dependency installed into the venv, and it is the reading the
recommendation rests on.

**6. The install command at the top of this page, from a clean virtualenv — both
commands.**

```text
$ pip install https://github.com/argszero/hermit-opencode/releases/download/0.2.0/hermit_opencode-0.2.0-py3-none-any.whl
Installing collected packages: PyYAML, hermit-opencode
Successfully installed PyYAML-6.0.3 hermit-opencode-0.2.0
$ hermit-opencode convert docs/_examples/file_adapter --output out/
  ... "omitted": [], "record": "hermit-opencode.json" }
EXIT CODE: 0
$ hermit-opencode deploy docs/_examples/file_adapter --workspace ws/
  ... "adapter_dir": ".opencode/adapter", "record": ".opencode/hermit-opencode.json" }
EXIT CODE: 0
```

`PyYAML 6.0.3` there is a dependency actually fetched from PyPI, not one
inherited from the host — this whole series runs with `PYTHONPATH` cleared, for
the reason the caveat in item 5 gives. The asset served from that URL hashes
identically to the one built here; the release notes carry the `sha256` of both
attached files, because a hash written into a file that the wheel itself contains
would change the very hash it states.

The output of that install is what readings C and 7 served. The whole chain —
download the wheel from the release URL, convert the example adapter, serve it
under `hermit-harness 0.2.0` from PyPI, `count_words` answering, the audit log
appended — was measured end to end with no `git` binary and no local checkout
anywhere in it. `deploy` was then measured through the same three steps.

**7. `deploy`, into a workspace that already had its own files.**

A project holding `main.py` and its own `AGENTS.md` was adopted with `--force`, by
the 0.2.0 build under test:

```text
$ hermit-opencode deploy tests/assets/file_adapter --workspace gate-ws --force
  "adapter_dir": ".opencode/adapter", "adopted": [], "server_name": "file_example",
  "tools": ["count_words"], "record": ".opencode/hermit-opencode.json"
```

`adopted` was empty because that project had no `opencode.json` to merge into;
the case that reports something is in the suite, where an `opencode.json` with a
`theme` key, its own `instructions` entry and a second MCP server survives the
merge with all three intact. `main.py` and `AGENTS.md` were byte-identical
afterwards — `AGENTS.md` because the context travels as `.opencode/context.md`
instead.

Then the command that deploy emitted, run **from the workspace**, with `cwd: "."`
and `PYTHONPATH` cleared, under `hermit-harness 0.2.0` from PyPI:

```text
$ hermit serve .opencode/adapter --audit-log .opencode/audit/tool-calls.jsonl
{"jsonrpc":"2.0","id":1,"result":{"capabilities":{...},"protocolVersion":"2024-11-05",
 "serverInfo":{"name":"file-example","version":"1.0"}}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"count_words", ...}]}}
EXIT CODE: 0
$ cat .opencode/audit/tool-calls.jsonl
{"time": "2026-11-06T06:46:50.480999+00:00", "adapter": "file-example", "version": "1.0",
 "tool": "count_words", "arguments": {"text": "one two three"}, "status": "ok", "result": {"count": 3}}
```

The audit log is the independent proof the call ran: it was written inside the
workspace, at the path the emitted entry names.

The suite covers what a single run cannot show: a second deploy is byte-identical
and leaves a user file, a user skill and the audit log untouched; a workspace the
tool did not create is refused with nothing written; `--force` adopts and reports;
and an `opencode.json` it cannot merge into stops it rather than being replaced.

### What was NOT verified

**No live OpenCode session has ever loaded this output — `convert`'s or
`deploy`'s.** There were no OpenCode credentials or model backend available while
this was built, so the end-to-end path stops at the MCP server: the configuration
is schema-valid and its server command works, but "OpenCode actually started, read
`.opencode/`, and used the skill and subagent" is **unproven**. A schema-valid
configuration is not a loaded one. If you run it and something is wrong, that is
exactly the report this repository wants.

**`deploy` deserves that caveat more than `convert` does**, because it writes into
a project you already have rather than into an empty directory of its own. So:
run it first in a fresh directory, or in a tree under version control, and treat
the guards above as the only promises — they bound what it writes, not what a
host does with it afterwards.

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

Both halves now exist as commands of this package. `convert` is the first,
`deploy` the second, and `deploy` writes into a workspace the way hermit's own
`deploy` does for its four hosts — using OpenCode's own places rather than a
managed block in `AGENTS.md`.

Hermit cannot host this itself: `hermit/plugins/__init__.py` is a hardcoded map
of four emitters with no entry points or registration hook, so a fifth host
cannot be added without changing hermit's core. A converter for a host hermit
does not yet support therefore has to ship its own command — which is what this
is.

The code descends from pull request #39, which was closed without being merged;
see `NOTICE` for what was derived and what changed.

Hermit pull request #42 proposes the same deploy route *inside hermit's core*
(`hermit/hosts/opencode.py`, `--host opencode`), and it was open and conflicting
when this was written. This package does not touch hermit's tree, so the two do
not compete for a merge: if that route lands upstream, this one remains the way to
reach OpenCode without changing hermit. What the two must not do is write the same
workspace — the collision is measured and written up in
[Relation to #42](https://github.com/Infini-AI-Lab/hermit/pull/39), where
`opencode.json` is written wholesale by both and the second writer silently wins.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
