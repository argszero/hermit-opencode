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

## Why not just `hermit convert`?

Because hermit has no OpenCode target. Measured 2026-11-11 against
`hermit-harness 0.2.0` — the latest release on PyPI — and against upstream
`main` at `1b0d897`, which is `main` *after* OpenCode landed there as a deploy
host (pull request #94, commit `1310de6`):

```text
$ hermit convert --adapter <adapter> --target opencode --output out/
hermit convert: error: argument --target: invalid choice: 'opencode'
                 (choose from claude-code, codex, pi, hermes)
```

Those four are a hardcoded map — `EMITTERS` in `hermit/plugins/__init__.py`, with
`TARGETS = tuple(EMITTERS)` — and there is no entry point or registration hook,
so a fifth host cannot be added from outside hermit. Bringing an adapter to
OpenCode therefore needs a command of its own, which is what this is.

What that means for you, and nothing more:

- **`hermit-harness 0.2.0` or later** wherever the tools are served from: the
  embedded adapter is in the `.hermit/` layout, and 0.1.0 reads `adapter.yaml` at
  the adapter root and refuses this one. The measurement is in
  [Requirements](#requirements--which-hermit-for-which-part).
- **`opencode 1.1.2` or later** loads this output — `opencode agent list` exits 0
  in a deployed workspace on 1.1.2 and on 1.19.5, against an empty-directory
  control that also exits 0 on each
  ([verification item 8](#verification--what-was-actually-run)). 1.1.2 is the
  oldest version this was checked on. This is **not** true of upstream's
  `hermit deploy --host opencode` output, which needs `opencode 1.18.27` or
  later; the bisect that found that floor is
  [verification item 9](#verification--what-was-actually-run), and what it means
  for a reader is in
  [Relation to hermit's own OpenCode work](#relation-to-hermits-own-opencode-work).
- **`deploy` wants a workspace you already have**, which `hermit convert` never
  asks for: it writes a directory of its own and leaves the copying to you. That
  is why `deploy` merges your `opencode.json` instead of replacing it, refuses a
  tree it did not create unless `--force`, and never deletes anything — see
  [What deploy does not do](#what-deploy-does-not-do).

## Install

Install the wheel attached to the [latest
release](https://github.com/argszero/hermit-opencode/releases):

```bash
pip install https://github.com/argszero/hermit-opencode/releases/download/0.2.4/hermit_opencode-0.2.4-py3-none-any.whl
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

**Every path in `opencode.json` is workspace-relative, on purpose.** OpenCode
expands no plugin-root variable, so a configuration that named this machine's
absolute paths would break the moment it was copied anywhere else. This is the
one constraint that shapes the whole output. The `mcp` entry also carries no
`cwd`, for a reason of its own: `opencode 1.1.2` rejects that key and refuses
the whole configuration with it, as [item 8](#verification--what-was-actually-run)
records.

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

**1. The suite: 26 passed, no network, no hermit installed.**

```text
tests/test_deploy.py::test_deploy_writes_the_four_parts_in_place PASSED
tests/test_deploy.py::test_a_workspace_this_tool_did_not_create_is_refused PASSED
tests/test_deploy.py::test_force_adopts_a_project_and_says_what_it_overwrote PASSED
tests/test_deploy.py::test_a_second_deploy_changes_nothing_it_generated PASSED
tests/test_deploy.py::test_deploy_refuses_a_config_it_cannot_merge_into PASSED
tests/test_deploy.py::test_deploy_refuses_an_opencode_json_that_is_not_json PASSED
tests/test_deploy.py::test_deploy_refuses_hooks_before_writing PASSED
tests/test_deploy.py::test_deploy_refuses_an_adapter_that_is_not_plugin_portable PASSED
tests/test_deploy.py::test_deploy_refuses_a_workspace_inside_the_adapter PASSED
tests/test_deploy.py::test_cli_deploys_and_the_old_positional_spelling_still_converts PASSED
tests/test_deploy.py::test_cli_reports_a_refused_workspace_with_exit_2 PASSED
tests/test_deploy.py::test_the_deployed_config_validates_against_the_opencode_schema PASSED
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
tests/test_emit.py::test_the_workspace_command_and_the_readme_agree_on_what_deploy_writes PASSED
tests/test_emit.py::test_the_output_is_something_opencode_actually_loads PASSED
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
--audit-log .opencode/audit/tool-calls.jsonl` — the server answered
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
`mcp` command run from the output directory. The adapter
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
commands.** 0.2.2, 0.2.3 and 0.2.4 change documentation only, so the runtime
readings below were taken on 0.2.1 and re-taken on 0.2.2, 0.2.3 and 0.2.4 with the
same result; the version here is the one you get from the URL at the top.

```text
$ pip install https://github.com/argszero/hermit-opencode/releases/download/0.2.4/hermit_opencode-0.2.4-py3-none-any.whl
Installing collected packages: PyYAML, hermit-opencode
Successfully installed PyYAML-6.0.3 hermit-opencode-0.2.4
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
the 0.2.4 build under test:

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

Then the command that deploy emitted, run **from the workspace**, with
`PYTHONPATH` cleared, under `hermit-harness 0.2.0` from PyPI:

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

**8. `opencode 1.1.2` loads a deployed workspace — and does not load it by
accident.** Items 1–7 prove the configuration is well-formed; none of them proves a
host reads it. This one does, and its first result was a failure, which is the
finding:

```text
$ opencode --version
1.1.2
$ opencode agent list                      # in a workspace deployed by 0.2.0
Error: Configuration is invalid at …/ws/opencode.json
↳ Invalid input mcp.file_example
EXIT CODE: 1
```

`--print-logs --log-level DEBUG` named the cause — the `cwd` key in the `mcp` entry:

```text
issues=[{"code":"invalid_union","errors":[[{"code":"unrecognized_keys",
 "keys":["cwd"],"message":"Unrecognized key: \"cwd\""}], …]}]
```

**A schema check could not have caught this.** OpenCode's *published* JSON schema
still documents `cwd` for a local MCP server, and the copy committed under
`tests/assets/` validates a configuration carrying it; the validator built into
1.1.2 is narrower than the schema the same project publishes. `0.2.0` shipped that
key, so a user of `0.2.0` had a configuration their OpenCode refused to start with.
`0.2.1` emits the entry without it, and the suite pins the keys it may carry.

With the key gone — the same CLI, the same workspace, nothing else changed:

```text
$ opencode agent list
build (primary)
compaction (primary)
explore (subagent)
general (subagent)
plan (primary)
summary (primary)
title (primary)
reviewer (subagent)
EXIT CODE: 0
```

Exit 0, and no configuration warning. `reviewer` is the subagent `exports.yaml`
declares, discovered from `.opencode/agents/reviewer.md`.

**The negative reading that makes the positive one evidence.** The same command, in
an empty directory with no `opencode.json` and no `.opencode/`:

```text
$ opencode agent list
build (primary)
compaction (primary)
explore (subagent)
general (subagent)
plan (primary)
summary (primary)
title (primary)
EXIT CODE: 0
```

Seven built-ins and no `reviewer`. The eighth line is therefore read from the
deployed files, not built into the CLI — which is the difference between "the
format looks right" and "the host read what we wrote".

**9. The version boundary: upstream's output does not load below `1.18.27`.**
Item 8 shows this package's output loading on 1.1.2. Running the same command
against a workspace written by `hermit deploy --host opencode`, from the same
`exports.yaml`, is where the two tools part:

```text
$ opencode agent list     # workspace written by `hermit deploy --host opencode`
1.1.2     Error: Configuration is invalid … Invalid input mcp.servers    EXIT 1
1.18.22   the same refusal, on the same key                             EXIT 1
1.18.27   agents listed                                                 EXIT 0
1.19.5    agents listed                                                 EXIT 0
```

Four installs of the CLI, one workspace, nothing else changed — and the
empty-directory control exits 0 on each of the four, so the refusals come from
the file. Upstream writes `{"mcp": {"servers": …}}` (`hermit/hosts/opencode.py` at
`9c45a65`); this package writes `mcp` keyed by server name. The boundary between
1.18.22 and 1.18.27 was not narrowed further, so `1.18.27` is the first version
*verified* to accept it rather than proven to be the first that can.

### What was NOT verified

**A model-driven session using these parts.** `opencode 1.1.2` reads the output —
the configuration parses and the adapter's subagent is discovered by
`opencode agent list` (item 8) — but no
provider credentials exist on the machine this was measured on, so nothing here
shows a model answering while calling the adapter's tool. That is the whole of the
remainder, and it is one sentence rather than a disclaimer about the format.
`opencode run` and `opencode auth login` are the two commands that would close it,
and both need a provider account.

Also unmeasured for that reason: whether OpenCode's tool-name handling rewrites
`file_example` into its own naming scheme in a session, and how it renders a
`description` containing non-ASCII text (emitted as a JSON string inside YAML
frontmatter — valid, still worth eyeballing).

**The exact opencode version where upstream's output starts loading.** That
boundary was bisected to a **range, not a version**: refused at `1.18.22`, accepted
at `1.18.27`, so it lies somewhere in `1.18.23`–`1.18.27`. `1.18.27` is the first
version verified to accept it, not proven to be the first that can. Two further
probes would settle one cell of it; the range is what is known and what the table
above states.

**And this finding could not be reported where it was found.** It is a fact about
`hermit deploy --host opencode`, so it belongs on hermit's issue #35 — but the
account this package is published from cannot write to that repository (its
owner blocked it: `GraphQL: User is blocked`, and the pull permission alone
remains). So it is recorded here instead, in the documentation of the tool that
works around it, because here is the only place it can be recorded.

**`deploy` writes into a project you already have**, rather than into an empty
directory of its own. Run it first in a fresh directory, or in a tree under version
control, and treat the guards above as the only promises — they bound what it
writes, not what a host does with it afterwards.
## Relation to hermit's own OpenCode work

Hermit's issue
[#35](https://github.com/Infini-AI-Lab/hermit/issues/35) asks for OpenCode as an
additional backend, in two halves: running tasks against an adapter
(`convert`), and deploying a trained adapter into a workspace (`deploy`). This
package is the first half, as a standalone tool.

Both halves now exist as commands of this package. `convert` is the first,
`deploy` the second, and `deploy` writes into a workspace the way hermit's own
`deploy` does for its hosts — using OpenCode's own places rather than a managed
block in `AGENTS.md`.

**Upstream's position, re-measured 2026-11-11 at `1b0d897`.** Pull request #42
proposed this route inside hermit's core and was closed unmerged, but the core
route was later built by someone else: pull request #94 (commit `1310de6`,
merged 2026-11-10) added `hermit/hosts/opencode.py` and a fifth `--host`
choice. **So `hermit deploy --host opencode` exists now, and if it works for
you, use it.** The rest of this section is the measurement of where it does and
does not.

*What upstream still does not do.* `hermit convert` has no OpenCode target:

```text
$ hermit convert --adapter <adapter> --target {claude-code,codex,pi,hermes}
```

Read at `1b0d897` from `hermit/cli.py:46` — five deploy hosts, four convert
targets. `EMITTERS` in `hermit/plugins/__init__.py:10` is still
`{"claude-code", "codex", "pi", "hermes"}`, with no entry point or registration
hook, so `convert` still cannot reach OpenCode from outside hermit. That half is
this package's alone, and it is what `convert` is for.

*What `deploy` still does differently.* One `lean_swarm` adapter into two empty
workspaces, upstream's `hermit deploy --host opencode` on one side and this
package's on the other, then both read back with `opencode agent list` beside an
empty-directory control:

| | upstream at `1b0d897` | this package |
|---|---|---|
| `opencode.json` `mcp` shape | `{"mcp": {"servers": {<name>: …}}}` | `{"mcp": {<name>: {…}}}` |
| `opencode 1.1.2` | **exit 1** — `Configuration is invalid … Invalid input mcp.servers` | exit 0 |
| `opencode 1.18.22` | **exit 1** — the same refusal | exit 0 |
| `opencode 1.18.27` | exit 0 | exit 0 |
| `opencode 1.19.5` | exit 0 | exit 0 |
| empty-directory control, on each of the four | exit 0 | exit 0 |
| server `command` | absolute paths: the install's `python`, the source adapter, `PYTHONPATH` at the hermit checkout | `hermit serve adapter` — relative to the workspace |
| context | a managed block inside `AGENTS.md` | `.opencode/context.md`, named under `instructions` in `opencode.json` |
| other keys emitted | `type`, `codemode`, `timeout.execution`, `environment` | `type`, `enabled` |

The `mcp.servers` key is the newer spelling and the published schema marks the
name-keyed form deprecated, so this is a version-range difference rather than a
feature one: upstream's output needs an opencode new enough to accept
`servers`, and 1.1.2 and 1.18.22 both refuse it at load. **The boundary was
bisected: refused at `1.18.22`, accepted at `1.18.27`, so it lies somewhere in
1.18.23–1.18.27; 1.18.27 is the first version this was verified to load on.**
This package's output loads on all four versions above, at the price of writing
the deprecated key. **A reader on `opencode 1.18.27` or later should prefer
`hermit deploy --host opencode`; below that, upstream's output does not load at
all and this package's does.**

The code descends from pull request #39, which was closed without being merged;
see `NOTICE` for what was derived and what changed.

Should both write the same workspace, the thing not to do is let them: that
collision was measured and is written up in
[Relation to #42](https://github.com/Infini-AI-Lab/hermit/pull/39) — `opencode.json`
written wholesale by both, the second writer silently winning, and #42's
`environment` block disappearing with it. Upstream's host writes `opencode.json`
wholesale, so deploying this package's output over it, or the reverse, replaces
the other's file rather than merging.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
