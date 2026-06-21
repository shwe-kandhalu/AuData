"""AuData Auditor as a Band agent (agent-to-agent mesh).

Band lets agents from any framework meet in shared chat rooms and coordinate via
@mentions. This exposes AuData's research-integrity auditor as a Band agent so it
can collaborate with other agents (e.g. a stats agent, an imaging agent) in a room.

Setup:
  1. Register an External Agent at https://app.band.ai/agents -> copy the
     Agent UUID and API key.
  2. Set BAND_AGENT_ID and BAND_API_KEY (in Backend/.env), then run:
         python -m audata.band_agent
"""

from __future__ import annotations

import asyncio
import os

_SYSTEM = (
    "You are the AuData Auditor, a biomedical research-integrity reviewer. In a Band room you "
    "coordinate with other agents and humans to audit a paper for statistical errors (p-value "
    "recomputation), numerical inconsistencies, image manipulation/duplication, methods-vs-claims "
    "overreach, and citation/reference problems. When asked to audit, lay out which checks apply, "
    "delegate to specialist agents via @mentions when present, and summarize findings with a "
    "severity and a precise locator (page or a verbatim quote) so a human can find each one. "
    "Be calibrated: flag only what the evidence supports; this is reviewer assistance, not a verdict."
)


def build():
    from band import Agent
    from band.adapters import AnthropicAdapter
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "Backend", ".env"))

    agent_id = os.getenv("BAND_AGENT_ID")
    api_key = os.getenv("BAND_API_KEY")
    if not (agent_id and api_key):
        raise RuntimeError("Set BAND_AGENT_ID and BAND_API_KEY (register an agent at app.band.ai/agents).")

    adapter = AnthropicAdapter(
        model=os.getenv("MODEL_REASONING") or "claude-sonnet-4-6",
        system_prompt=_SYSTEM,
    )
    return Agent.create(adapter=adapter, agent_id=agent_id, api_key=api_key)


async def _main():
    agent = build()
    print(f"AuData Auditor live on Band — address {getattr(agent, 'address', '?')}")
    await agent.run()


if __name__ == "__main__":
    asyncio.run(_main())
