"""Bring a hermit adapter to OpenCode: convert it into a configuration, or deploy it into a workspace."""
from __future__ import annotations

__version__ = "0.2.0"

from .deploy import WorkspaceError, deploy  # noqa: E402
from .emit import SERVER_COMMAND, Unsupported, build  # noqa: E402
from .manifest import AdapterError  # noqa: E402

__all__ = ["SERVER_COMMAND", "AdapterError", "Unsupported", "WorkspaceError", "build", "deploy", "__version__"]
