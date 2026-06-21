"""Build a downloadable Word (.docx) audit report that synthesizes every
detector's findings for a paper: Statistical Recompute (p-values), Meta-analysis,
Numerical Consistency, Image Forensics, Methods<->Claims, and Reference Integrity.

Reads the persisted per-paper audit stages (the same data the UI Audit Report
shows) and renders a structured Word document.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List

from . import storage

_SEV_RANK = {"high": 4, "medium": 3, "moderate": 3, "low": 2, "info": 1, "none": 0}


def _sev(x: Any) -> str:
    s = (str(x) if x else "medium").lower()
    return "medium" if s == "moderate" else s


def _norm(key: str, d: Any) -> Dict[str, Any]:
    """Normalize one stage's data -> {ran, total, flagged, items:[{title,severity,detail}], note}."""
    if not d:
        return {"ran": False}
    items: List[Dict[str, str]] = []
    if key == "references":
        res = d.get("results", []) or []
        fl = [r for r in res if r.get("status") == "flagged"]
        for r in fl:
            title = (r.get("matched") or {}).get("title") or (r.get("input") or {}).get("raw") or f"Reference {r.get('number','')}"
            items.append({"title": title, "severity": _sev(r.get("severity")),
                          "detail": "; ".join(i.get("label", "") for i in (r.get("issues") or []))})
        return {"ran": True, "total": (d.get("summary") or {}).get("total", len(res)),
                "flagged": (d.get("summary") or {}).get("flagged", len(fl)), "items": items}
    if key == "methods":
        res = d.get("results", []) or []
        fl = [r for r in res if r.get("status") == "flagged"]
        for r in fl:
            items.append({"title": r.get("claim", ""), "severity": _sev(r.get("severity")),
                          "detail": " - ".join(x for x in (r.get("issue_type"), r.get("reasoning")) if x)})
        return {"ran": True, "total": (d.get("summary") or {}).get("total", len(res)),
                "flagged": (d.get("summary") or {}).get("flagged", len(fl)), "items": items}
    if key == "statcheck":
        f = d.get("findings", []) or []
        fl = [x for x in f if x.get("status") == "mismatch"]
        for x in fl:
            items.append({"title": x.get("claim", ""), "severity": "high",
                          "detail": x.get("note", "Reported p-value does not match the recomputed value.")})
        return {"ran": True, "total": d.get("claim_count", len(f)),
                "flagged": d.get("mismatch_count", len(fl)), "items": items}
    if key == "numerical":
        flags = d.get("flags", []) or []
        for x in flags:
            items.append({"title": x.get("description") or x.get("type") or "Inconsistency",
                          "severity": _sev(x.get("severity")),
                          "detail": f'"{x.get("excerpt")}"' if x.get("excerpt") else (x.get("type") or "")})
        return {"ran": True, "total": len(flags), "flagged": len(flags), "items": items}
    if key == "images":
        summ = d.get("summary") or {}
        report = d.get("report") or {}
        for fnd in (report.get("cross_paper_findings") or []):
            score = fnd.get("similarity_score")
            items.append({"title": f"{fnd.get('flag_type','Figure reuse')}: {fnd.get('target_figure','')} ~ {fnd.get('candidate_figure','')}",
                          "severity": _sev(fnd.get("severity")),
                          "detail": f"cross-paper similarity {score:.2f}" if isinstance(score, (int, float)) else f"cross-paper similarity {score}"})
        for r in (report.get("figure_forensics") or []):
            fig = f"page {r.get('metadata',{}).get('page')}" if r.get("metadata", {}).get("page") else "a figure"
            cm = r.get("copy_move_result") or {}
            sp = r.get("splice_result") or {}
            if cm.get("severity") and cm["severity"] not in ("low", "none"):
                items.append({"title": f"Copy-move in {fig}", "severity": _sev(cm["severity"]), "detail": "Cloned region detected within the figure."})
            if sp.get("severity") and sp["severity"] not in ("low", "none"):
                items.append({"title": f"Splice boundary in {fig}", "severity": _sev(sp["severity"]), "detail": "Possible splice / edited boundary."})
            ai = r.get("ai_generated_score")
            if isinstance(ai, (int, float)) and ai >= 0.7:
                items.append({"title": f"Possibly AI-generated ({fig})", "severity": "medium", "detail": f"heuristic score {ai:.2f}"})
        return {"ran": True, "total": summ.get("total_images", report.get("num_target_figures", 0)),
                "flagged": summ.get("flagged", len(items)), "items": items}
    if key == "meta":
        if not d.get("detected"):
            return {"ran": True, "total": 0, "flagged": 0, "items": [], "note": "No meta-analysis detected in this paper."}
        disc = d.get("verdict") == "discrepancy"
        if disc:
            items.append({"title": f"Pooled {d.get('measure','')} discrepancy", "severity": _sev(d.get("severity")),
                          "detail": d.get("explanation", "")})
        return {"ran": True, "total": 1, "flagged": 1 if disc else 0, "items": items,
                "note": None if disc else d.get("explanation")}
    return {"ran": False}


_SECTIONS = [
    ("statcheck", "Statistical Recompute - p-values"),
    ("meta", "Meta-analysis recreation"),
    ("numerical", "Numerical Consistency"),
    ("images", "Image Forensics"),
    ("methods", "Methods <-> Claims"),
    ("references", "Reference Integrity"),
]


def build_docx(paper_id: str) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    paper = storage.get_paper(paper_id) or {}
    audits = storage.get_paper_audits(paper_id) or {}
    sections = [(label, _norm(key, audits.get(key))) for key, label in _SECTIONS]
    run_sections = [(l, n) for l, n in sections if n.get("ran")]
    total_flagged = sum(n.get("flagged", 0) for _, n in run_sections)
    by_sev: Dict[str, int] = {}
    for _, n in run_sections:
        for it in n.get("items", []):
            by_sev[it["severity"]] = by_sev.get(it["severity"], 0) + 1

    doc = Document()
    doc.add_heading("AuData Audit Report", level=0)
    doc.add_heading(paper.get("title") or paper_id, level=1)
    meta_line = " · ".join(str(x) for x in (paper.get("authors"), paper.get("year"), paper.get("container")) if x)
    if meta_line:
        doc.add_paragraph(meta_line)
    doc.add_paragraph(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    p = doc.add_paragraph()
    run = p.add_run(f"{total_flagged} flag{'' if total_flagged == 1 else 's'} across {len(run_sections)} detector{'' if len(run_sections) == 1 else 's'} run.")
    run.bold = True
    if by_sev:
        doc.add_paragraph("Severity: " + ", ".join(f"{by_sev[k]} {k}" for k in ("high", "medium", "low", "info") if by_sev.get(k)))

    if not run_sections:
        doc.add_paragraph("No detectors have been run for this paper yet.")

    sev_color = {"high": RGBColor(0xC0, 0x21, 0x21), "medium": RGBColor(0xB4, 0x53, 0x09),
                 "low": RGBColor(0x0B, 0x72, 0x85), "info": RGBColor(0x57, 0x57, 0x57), "none": RGBColor(0x1A, 0x7F, 0x37)}

    for label, n in sections:
        if not n.get("ran"):
            continue
        h = doc.add_heading(label, level=2)
        cnt = doc.add_paragraph()
        c = cnt.add_run(f"{n.get('flagged', 0)} flagged" + (f" of {n['total']}" if n.get("total") else ""))
        c.italic = True
        items = sorted(n.get("items", []), key=lambda it: -_SEV_RANK.get(it["severity"], 0))
        if items:
            for it in items:
                para = doc.add_paragraph(style="List Bullet")
                sr = para.add_run(f"[{it['severity'].upper()}] ")
                sr.bold = True
                sr.font.color.rgb = sev_color.get(it["severity"], RGBColor(0, 0, 0))
                para.add_run(it["title"])
                if it.get("detail"):
                    para.add_run(f" - {it['detail']}").italic = True
        else:
            doc.add_paragraph(n.get("note") or f"No issues found ({n.get('total', 0)} checked).")

    doc.add_paragraph()
    foot = doc.add_paragraph()
    fr = foot.add_run("Generated by AuData. Flags are decision support for a human reviewer, not determinations of misconduct.")
    fr.italic = True
    fr.font.size = Pt(8)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
