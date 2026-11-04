"""Convert a hermit adapter into an OpenCode configuration."""
from __future__ import annotations

__version__ = "0.1.1"

from .emit import SERVER_COMMAND, Unsupported, build  # noqa: E402
from .manifest import AdapterError  # noqa: E402

__all__ = ["SERVER_COMMAND", "AdapterError", "Unsupported", "build", "__version__"]
