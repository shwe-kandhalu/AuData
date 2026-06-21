"""Band integration status.

Band is an agent-to-agent chat mesh (band-sdk); the runnable agent lives in
audata.band_agent (`python -m audata.band_agent`). "Active" means an agent is
registered (BAND_AGENT_ID + BAND_API_KEY) and the SDK is installed.
"""

from __future__ import annotations

import importlib.util
import os


def available() -> bool:
    return bool(os.getenv("BAND_AGENT_ID") and os.getenv("BAND_API_KEY")
                and importlib.util.find_spec("band"))


def relay(*_args, **_kwargs) -> bool:
    # Legacy no-op: Band is a chat mesh, not an HTTP relay. Kept so callers don't break.
    return False
