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
            vlm = r.get("vlm_result") or {}
            if vlm.get("verdict") and vlm["verdict"] != "clean" and (vlm.get("confidence") or 0) >= 0.5:
                label = "possibly AI-generated" if vlm["verdict"] == "ai_generated" else "manipulation suspected"
                items.append({"title": f"Vision model: {label} ({fig})", "severity": "medium", "detail": vlm.get("reason", "")})
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


# ── docx styling helpers ───────────────────────────────────────────────────────

# (fill hex, text RGB) per tone — light boxes with strong text, matching the UI.
_TONE = {
    "high":   ("F8D7DA", (0xC0, 0x21, 0x21)),
    "medium": ("FFE8CC", (0xB4, 0x53, 0x09)),
    "low":    ("D6EAF8", (0x0B, 0x72, 0x85)),
    "info":   ("ECECEC", (0x57, 0x57, 0x57)),
    "none":   ("D4EDDA", (0x1A, 0x7F, 0x37)),
    "green":  ("D4EDDA", (0x1A, 0x7F, 0x37)),
    "amber":  ("FFE8CC", (0xB4, 0x53, 0x09)),
    "slate":  ("EEF1F5", (0x33, 0x33, 0x33)),
    "blue":   ("E7F0FF", (0x1D, 0x4E, 0xD8)),
}


def _shade(cell, fill_hex: str) -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tcPr.append(shd)


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
    clean = bool(run_sections) and total_flagged == 0

    doc = Document()
    doc.add_heading("AuData Audit Report", level=0)
    doc.add_heading(paper.get("title") or paper_id, level=1)
    meta_line = " · ".join(str(x) for x in (paper.get("authors"), paper.get("year"), paper.get("container")) if x)
    if meta_line:
        doc.add_paragraph(meta_line)
    gp = doc.add_paragraph()
    gr = gp.add_run(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    gr.italic = True
    gr.font.size = Pt(8)
    gr.font.color.rgb = RGBColor(0x70, 0x70, 0x70)

    def _box_run(cell, text, rgb, bold=True, size=None, italic=False):
        para = cell.paragraphs[0] if not cell.paragraphs[0].runs and not cell.paragraphs[0].text else cell.add_paragraph()
        r = para.add_run(text)
        r.bold = bold
        r.italic = italic
        if size:
            r.font.size = Pt(size)
        if rgb:
            r.font.color.rgb = RGBColor(*rgb)
        return para

    # ── verdict banner ──
    if run_sections:
        tone = "green" if clean else "amber"
        bt = doc.add_table(rows=1, cols=1)
        bc = bt.rows[0].cells[0]
        _shade(bc, _TONE[tone][0])
        sym = "✓ " if clean else "⚠ "
        verdict = ("No integrity issues detected" if clean
                   else f"{total_flagged} potential issue{'' if total_flagged == 1 else 's'} flagged for review")
        _box_run(bc, sym + verdict, _TONE[tone][1], bold=True, size=12)
        _box_run(bc, f"across {len(run_sections)} of {len(_SECTIONS)} detectors run", (0x57, 0x57, 0x57), bold=False, size=9)

    # ── stat boxes ──
    stat_defs = [("Total flags", total_flagged, "amber" if total_flagged else "green"),
                 ("High", by_sev.get("high", 0), "high"),
                 ("Medium", by_sev.get("medium", 0), "medium"),
                 ("Low", by_sev.get("low", 0), "low"),
                 ("Detectors", len(run_sections), "slate")]
    st = doc.add_table(rows=1, cols=len(stat_defs))
    for i, (label, val, tone) in enumerate(stat_defs):
        c = st.rows[0].cells[i]
        _shade(c, _TONE[tone][0])
        val_txt = f"{val}/{len(_SECTIONS)}" if label == "Detectors" else str(val)
        _box_run(c, val_txt, _TONE[tone][1], bold=True, size=20)
        _box_run(c, label.upper(), (0x57, 0x57, 0x57), bold=False, size=8)

    # ── detector status grid (3 columns) ──
    doc.add_heading("Detectors", level=2)
    cols = 3
    import math
    rows = max(1, math.ceil(len(sections) / cols))
    grid = doc.add_table(rows=rows, cols=cols)
    grid.style = "Table Grid"
    for idx, (label, n) in enumerate(sections):
        r, c = divmod(idx, cols)
        cell = grid.cell(r, c)
        ran = n.get("ran")
        flagged = n.get("flagged", 0)
        if not ran:
            tone, sym, status = "slate", "○", "Not run"
        elif flagged:
            tone, sym, status = "amber", "⚠", f"{flagged} flag{'' if flagged == 1 else 's'}"
        else:
            tone, sym, status = "green", "✓", "Clean"
        _shade(cell, _TONE[tone][0])
        _box_run(cell, f"{sym} {label}", _TONE[tone][1], bold=True, size=10)
        _box_run(cell, status, (0x57, 0x57, 0x57), bold=False, size=9)
    # blank any unused trailing cells
    for idx in range(len(sections), rows * cols):
        r, c = divmod(idx, cols)
        _shade(grid.cell(r, c), "FFFFFF")

    # ── findings (only flagged detectors) ──
    if any(n.get("flagged") for _, n in run_sections):
        doc.add_heading("Findings", level=2)
        for label, n in sections:
            if not n.get("ran") or not n.get("flagged"):
                continue
            doc.add_heading(f"{label}  —  {n.get('flagged', 0)} flagged"
                            + (f" of {n['total']}" if n.get("total") else ""), level=3)
            items = sorted(n.get("items", []), key=lambda it: -_SEV_RANK.get(it["severity"], 0))
            ft = doc.add_table(rows=len(items), cols=1)
            ft.style = "Table Grid"
            for i, it in enumerate(items):
                cell = ft.rows[i].cells[0]
                _shade(cell, _TONE.get(it["severity"], _TONE["info"])[0])
                p0 = cell.paragraphs[0]
                pill = p0.add_run(f"[{it['severity'].upper()}]  ")
                pill.bold = True
                pill.font.color.rgb = RGBColor(*_TONE.get(it["severity"], _TONE["info"])[1])
                title = p0.add_run(it["title"])
                title.bold = True
                if it.get("detail"):
                    dp = cell.add_paragraph()
                    dr = dp.add_run(it["detail"])
                    dr.font.size = Pt(9)
                    dr.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    # ── passed checks ──
    passed = [label for label, n in sections if n.get("ran") and not n.get("flagged")]
    if passed:
        doc.add_heading("Passed checks", level=2)
        pt = doc.add_table(rows=1, cols=1)
        pc = pt.rows[0].cells[0]
        _shade(pc, _TONE["green"][0])
        _box_run(pc, "✓ " + "    ✓ ".join(passed), _TONE["green"][1], bold=True, size=10)

    if not run_sections:
        doc.add_paragraph("No detectors have been run for this paper yet.")

    doc.add_paragraph()
    foot = doc.add_paragraph()
    fr = foot.add_run("Generated by AuData. Flags are decision support for a human reviewer, not determinations of misconduct.")
    fr.italic = True
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor(0x70, 0x70, 0x70)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
