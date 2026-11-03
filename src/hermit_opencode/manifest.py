"""Read an adapter's manifest, in both layouts Hermit has shipped.

An adapter is a directory of files. Its template's metadata lives either in
`.hermit/adapter.yaml` (Hermit 0.1.0 and later, `contract: "2"`) beside an
`exports.yaml` at the root, or in one `adapter.yaml` at the root that holds the
template and an `exports:` section (Hermit 0.1, `contract: "1"`). Both are read
here so one converter serves adapters written against either.

Nothing in this module imports Hermit: the layout is a file format, and a
converter only has to read it.
"""
from __future__ import annotations

from pathlib import Path
import re

import yaml

META = ".hermit"
MANIFEST_V2 = f"{META}/adapter.yaml"     # contract 2: metadata only
MANIFEST_V1 = "adapter.yaml"             # contract 1: metadata and exports together
EXPORTS = "exports.yaml"                 # contract 2: what the acting agent receives
CONTEXT = "ADAPTER.md"                   # a fixed name, always exported, optional
PORTABLE = "plugin-portable"             # false: the adapter works through hermit only
SLUG = re.compile(r"[a-z][a-z0-9-]{0,63}")


class AdapterError(ValueError):
    """An adapter this converter cannot read, and why."""


def layout(root: Path) -> int:
    """Which manifest layout the adapter at `root` uses: 2 or 1."""
    root = Path(root)
    if (root / MANIFEST_V2).is_file():
        return 2
    if (root / MANIFEST_V1).is_file():
        return 1
    raise AdapterError(
        f"{root} is not an adapter: it has neither {MANIFEST_V2} (Hermit 0.1.0 and later) "
        f"nor {MANIFEST_V1} (Hermit 0.1) at its root")


def _yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise AdapterError(f"{path.name} is not valid YAML: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise AdapterError(f"{path.name} must be a mapping")
    return data


def _identity(template, where: str) -> dict:
    if not isinstance(template, dict):
        raise AdapterError(f"{where} needs a template section")
    ident = str(template.get("id", ""))
    if not SLUG.fullmatch(ident):
        raise AdapterError(f"{where}: template.id must be a lowercase slug, not {ident!r}")
    version = template.get("version")
    if not isinstance(version, str) or not version.strip():
        raise AdapterError(f"{where}: template.version must be a nonempty string")
    return {"id": ident, "name": template.get("name", ident), "version": version}


def read(root: Path) -> dict:
    """The adapter's exports with its identity, whatever layout it uses.

    Returns the keys the emitter needs: `id`, `name`, `version`, `context`,
    `plugin-portable`, `layout`, plus whatever the exports declare (`agents`,
    `skills`, `tools`, `hooks`, `internal`, `context_tool`).
    """
    root = Path(root).resolve()
    where = layout(root)
    if where == 2:
        meta = _yaml(root / MANIFEST_V2)
        exports = _yaml(root / EXPORTS)
        source = MANIFEST_V2
    else:
        data = _yaml(root / MANIFEST_V1)
        # The exports section is the adapter's content; `origin` is the Trainer's own bookkeeping.
        exports = data.get("exports") or {}
        meta = {key: value for key, value in data.items() if key not in ("exports", "origin")}
        source = MANIFEST_V1
    if not isinstance(exports, dict):
        raise AdapterError(f"{source}: the exports section must be a mapping")
    if exports.get("context", CONTEXT) != CONTEXT:
        raise AdapterError(f"the context is always {CONTEXT}; the exports may only name it")
    out = dict(exports)
    out.update(_identity(meta.get("template"), source))
    out["context"] = CONTEXT
    out[PORTABLE] = meta.get(PORTABLE, True)
    out["layout"] = where
    return out
