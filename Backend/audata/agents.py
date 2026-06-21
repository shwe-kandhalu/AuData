"""Fetch.ai uAgent layer for AuData.

Wraps the existing detectors so they can be invoked agent-to-agent (and made
discoverable on ASI:One). Each detector run is a message handler that reuses the
same backend functions the HTTP API uses, so there is one source of truth.

Run it as its own process:

    python -m audata.agents

Config (env):
    FETCH_AGENT_SEED     deterministic identity seed (default: dev seed)
    FETCH_AGENT_PORT     local port (default 8011)
    FETCH_AGENT_MAILBOX  Agentverse mailbox key (optional; enables ASI:One)
    BAND_API_KEY/...     if set, replies are also relayed through Band (band.py)
"""

from __future__ import annotations

import os
from typing import Any, Dict

from uagents import Agent, Context, Model


class AuditRequest(Model):
    paper_id: str
    detector: str          # statcheck | meta | numerical | images | methods | references | all


class AuditResponse(Model):
    detector: str
    ok: bool
    summary: Dict[str, Any]
    note: str = ""


def _run_detector(detector: str, paper_id: str) -> Dict[str, Any]:
    """Reuse the same logic as the HTTP endpoints; returns a per-detector summary."""
    from . import storage, llm
    paper = storage.get_paper(paper_id)
    if not paper:
        return {"ok": False, "note": "paper not found"}
    model = llm.get_model_for(llm.TASK_REASONING) or llm.get_model_for(llm.TASK_EXTRACTION)

    if detector == "numerical":
        from . import numerical as nu
        r = nu.analyze(paper, model)
        storage.save_paper_audit(paper_id, "numerical", r)
        return {"ok": True, "summary": r.get("summary", {})}
    if detector == "meta":
        from . import meta_analysis as ma
        r = ma.analyze(paper, model)
        storage.save_paper_audit(paper_id, "meta", r)
        return {"ok": True, "summary": {"detected": r.get("detected"), "verdict": r.get("verdict")}}
    if detector == "references":
        from . import reference_integrity as refint
        prepared = refint.prepare_paper_references(paper)
        results = [refint.check_reference(i, p["doi"], p["raw"], p["claim"], model, True, p["ctx"], p["number"])
                   for i, p in enumerate(prepared)]
        data = {"results": results, "summary": refint.summarize(results), "metrics": refint.paper_metrics(results)}
        storage.save_paper_audit(paper_id, "references", data)
        return {"ok": True, "summary": data["summary"]}
    if detector == "methods":
        from . import methods_claims as mc
        claims = mc.extract_claims(paper, model)
        ev = mc._evidence_context(paper)
        results = [mc.check_claim(i, c["claim"], c.get("quote", ""), ev, model) for i, c in enumerate(claims)]
        data = {"results": results, "summary": mc.summarize(results)}
        storage.save_paper_audit(paper_id, "methods", data)
        return {"ok": True, "summary": data["summary"]}
    if detector == "images":
        from . import imageforensicsagents as imgf
        candidates = [p for p in storage.list_papers(limit=50) if p.get("id") != paper_id and p.get("has_pdf")][:10]
        report = imgf.run_image_integrity_agent_from_papers(paper, candidates, output_root=str(os.path.expanduser("~/.audata/forensics/" + paper_id)))
        summary = imgf.summarize_forensics_results(report.get("figure_forensics", []))
        storage.save_paper_audit(paper_id, "images", {"summary": summary, "report": report})
        return {"ok": True, "summary": summary}
    return {"ok": False, "note": f"unknown detector '{detector}'"}


def build_agent() -> Agent:
    agent = Agent(
        name="audata-auditor",
        seed=os.getenv("FETCH_AGENT_SEED", "audata-dev-seed-change-me"),
        port=int(os.getenv("FETCH_AGENT_PORT", "8011")),
        endpoint=[f"http://127.0.0.1:{os.getenv('FETCH_AGENT_PORT', '8011')}/submit"],
        mailbox=os.getenv("FETCH_AGENT_MAILBOX") or None,
    )

    @agent.on_event("startup")
    async def _hello(ctx: Context):
        ctx.logger.info(f"AuData auditor agent up — address {agent.address}")

    @agent.on_message(model=AuditRequest, replies=AuditResponse)
    async def _on_audit(ctx: Context, sender: str, msg: AuditRequest):
        ctx.logger.info(f"audit request from {sender}: {msg.detector} on {msg.paper_id}")
        detectors = (["statcheck", "meta", "numerical", "images", "methods", "references"]
                     if msg.detector == "all" else [msg.detector])
        for det in detectors:
            try:
                res = _run_detector(det, msg.paper_id)
            except Exception as e:
                res = {"ok": False, "note": str(e)}
            resp = AuditResponse(detector=det, ok=bool(res.get("ok")),
                                 summary=res.get("summary", {}), note=res.get("note", ""))
            await ctx.send(sender, resp)

    return agent


if __name__ == "__main__":
    build_agent().run()
