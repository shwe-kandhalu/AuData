"""Band agent-to-agent messaging relay (gated, no-op unless configured).

When BAND_API_KEY (+ BAND_ENDPOINT) are set, detector results emitted by the
Fetch uAgent (agents.py) are also relayed onto a Band channel so other agents
can subscribe. Without config this is a silent no-op, so it never breaks runs.

Set BAND_ENDPOINT to the channel/publish URL and BAND_CHANNEL to the topic.
"""

from __future__ import annotations

import os
from typing import Any, Dict


def available() -> bool:
    return bool(os.getenv("BAND_API_KEY") and os.getenv("BAND_ENDPOINT"))


def relay(topic: str, payload: Dict[str, Any]) -> bool:
    if not available():
        return False
    try:
        import requests
        r = requests.post(
            os.getenv("BAND_ENDPOINT"),
            headers={"Authorization": f"Bearer {os.getenv('BAND_API_KEY')}", "Content-Type": "application/json"},
            json={"channel": os.getenv("BAND_CHANNEL", "audata"), "topic": topic, "payload": payload},
            timeout=8,
        )
        return r.status_code < 300
    except Exception as e:
        print(f"[audata.band] relay failed: {e}")
        return False
