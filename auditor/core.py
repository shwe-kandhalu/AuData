from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from scipy import stats

from .claims import StatisticalClaim, extract_claims


DEFAULT_TOLERANCE = 0.001


@dataclass(frozen=True)
class EvidenceTrace:
    page: int | None
    section: str | None
    quote: str
    start_char: int
    end_char: int
    exact_quote: str
    quote_start_char: int
    quote_end_char: int
    surrounding_context: str
    bbox: dict[str, float] | None = None
    bboxes: list[dict[str, float]] | None = None

    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "section": self.section,
            "quote": self.quote,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "exact_quote": self.exact_quote,
            "quote_start_char": self.quote_start_char,
            "quote_end_char": self.quote_end_char,
            "surrounding_context": self.surrounding_context,
            "bbox": self.bbox,
            "bboxes": self.bboxes or [],
        }


@dataclass(frozen=True)
class MathTrace:
    test: str
    formula: str
    inputs: dict[str, float | int]
    substitution: str
    result: float

    def to_dict(self) -> dict:
        return {
            "test": self.test,
            "formula": self.formula,
            "inputs": self.inputs,
            "substitution": self.substitution,
            "result": self.result,
        }


@dataclass(frozen=True)
class AuditFinding:
    status: str
    claim: str
    reported_p: str
    recomputed_p: float
    difference: float
    confidence: str
    evidence: EvidenceTrace
    math: MathTrace
    note: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "claim": self.claim,
            "reported_p": self.reported_p,
            "recomputed_p": self.recomputed_p,
            "difference": self.difference,
            "confidence": self.confidence,
            "evidence": self.evidence.to_dict(),
            "math": self.math.to_dict(),
            "note": self.note,
        }


@dataclass(frozen=True)
class WordSpan:
    start_char: int
    end_char: int
    bbox: dict[str, float]


@dataclass(frozen=True)
class PageSpan:
    page: int
    start_char: int
    end_char: int
    text: str
    bboxes_by_quote: dict[tuple[int, int], list[dict[str, float]]]
    word_spans: list[WordSpan]


SECTION_RE = re.compile(
    r"^\s*(?:\d{0,2}[.)]?\s*)?"
    r"(abstract|introduction|background|methods|materials and methods|methodology|"
    r"results|results and discussion|discussion|conclusion|conclusions|references|appendix)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)


def _rect_to_dict(rect: fitz.Rect) -> dict[str, float]:
    return {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1}


def _merge_boxes_by_line(boxes: list[dict[str, float]]) -> list[dict[str, float]]:
    lines: list[dict[str, float]] = []
    for box in boxes:
        y_mid = (box["y0"] + box["y1"]) / 2
        target = None
        for line in lines:
            line_mid = (line["y0"] + line["y1"]) / 2
            overlaps = box["y0"] <= line["y1"] and box["y1"] >= line["y0"]
            if overlaps or abs(y_mid - line_mid) <= 4:
                target = line
                break
        if target is None:
            lines.append(dict(box))
            continue
        target["x0"] = min(target["x0"], box["x0"])
        target["y0"] = min(target["y0"], box["y0"])
        target["x1"] = max(target["x1"], box["x1"])
        target["y1"] = max(target["y1"], box["y1"])
    return sorted(lines, key=lambda item: (item["y0"], item["x0"]))


def _section_for_offset(text: str, offset: int) -> str | None:
    section = None
    for line in text[:offset].splitlines():
        match = SECTION_RE.match(line)
        if match:
            section = match.group(1).strip().title()
    return section


def _format_reported_p(claim: StatisticalClaim) -> str:
    return f"{claim.comparator}{claim.reported_p:g}"


def _clean_quote(text: str) -> str:
    return " ".join(text.split())


def _sentence_context(text: str, start: int, end: int) -> tuple[str, int, int, str]:
    left_window = max(0, start - 800)
    right_window = min(len(text), end + 800)
    left = text[left_window:start]
    right = text[end:right_window]

    sentence_start = left_window
    for match in re.finditer(r"[.!?]\s+|\n\s*\n", left):
        sentence_start = left_window + match.end()
    heading_break = text[sentence_start:start].rfind("\n")
    if heading_break >= 0:
        possible_heading = text[sentence_start:sentence_start + heading_break]
        if SECTION_RE.match(possible_heading):
            sentence_start = sentence_start + heading_break + 1
    prefix = text[sentence_start:start]
    paragraph_breaks = list(re.finditer(r"\n\s*\n", prefix))
    if paragraph_breaks:
        sentence_start = sentence_start + paragraph_breaks[-1].end()
        prefix = text[sentence_start:start]
    first_line_end = prefix.find("\n")
    if first_line_end >= 0 and SECTION_RE.match(prefix[:first_line_end]):
        sentence_start = sentence_start + first_line_end + 1
        prefix = text[sentence_start:start]
    line_offset = 0
    for line in prefix.splitlines(keepends=True):
        if SECTION_RE.match(line.strip()):
            sentence_start = sentence_start + line_offset + len(line)
        line_offset += len(line)

    sentence_end = right_window
    match = re.search(r"[.!?](?:\s|$)|\n\s*\n", right)
    if match:
        sentence_end = end + match.end()

    quote = _clean_quote(text[sentence_start:sentence_end])
    surrounding = _clean_quote(text[max(0, sentence_start - 220):min(len(text), sentence_end + 220)])
    return quote, sentence_start, sentence_end, surrounding


def _extract_pdf_with_trace(pdf: str | Path | bytes) -> tuple[str, list[PageSpan]]:
    if isinstance(pdf, bytes):
        doc = fitz.open(stream=pdf, filetype="pdf")
    else:
        doc = fitz.open(Path(pdf))

    try:
        full_parts: list[str] = []
        page_spans: list[PageSpan] = []
        cursor = 0
        for index, page in enumerate(doc):
            text = page.get_text("text")
            page_start = cursor
            page_end = page_start + len(text)
            local_claims = extract_claims(text)
            bboxes_by_quote: dict[tuple[int, int], list[dict[str, float]]] = {}
            for claim in local_claims:
                rects = page.search_for(claim.raw)
                bboxes_by_quote[(page_start + claim.start_char, page_start + claim.end_char)] = [
                    _rect_to_dict(rect) for rect in rects
                ]
            word_spans: list[WordSpan] = []
            search_from = 0
            for word in page.get_text("words"):
                word_text = str(word[4])
                if not word_text:
                    continue
                local_start = text.find(word_text, search_from)
                if local_start < 0:
                    local_start = text.find(word_text)
                if local_start < 0:
                    continue
                local_end = local_start + len(word_text)
                search_from = local_end
                word_spans.append(
                    WordSpan(
                        start_char=page_start + local_start,
                        end_char=page_start + local_end,
                        bbox={"x0": float(word[0]), "y0": float(word[1]), "x1": float(word[2]), "y1": float(word[3])},
                    )
                )
            page_spans.append(
                PageSpan(
                    page=index + 1,
                    start_char=page_start,
                    end_char=page_end,
                    text=text,
                    bboxes_by_quote=bboxes_by_quote,
                    word_spans=word_spans,
                )
            )
            full_parts.append(text)
            cursor = page_end
            if index < doc.page_count - 1:
                full_parts.append("\n")
                cursor += 1
        return "".join(full_parts), page_spans
    finally:
        doc.close()


def extract_pdf_text(path: str | Path) -> str:
    text, _ = _extract_pdf_with_trace(path)
    return text


def recompute_p_value(claim: StatisticalClaim) -> float:
    return recompute_math_trace(claim).result


def recompute_math_trace(claim: StatisticalClaim) -> MathTrace:
    if claim.kind == "t":
        if claim.df1 is None:
            raise ValueError("t claim is missing degrees of freedom")
        result = float(stats.t.sf(abs(claim.statistic), claim.df1) * 2)
        return MathTrace(
            test="two_tailed_t_test",
            formula="p = 2 * (1 - t.cdf(abs(t), df))",
            inputs={"t": claim.statistic, "df": claim.df1},
            substitution=f"p = 2 * (1 - t.cdf({abs(claim.statistic):g}, {claim.df1}))",
            result=result,
        )

    if claim.kind == "F":
        if claim.df1 is None or claim.df2 is None:
            raise ValueError("F claim is missing degrees of freedom")
        result = float(stats.f.sf(claim.statistic, claim.df1, claim.df2))
        return MathTrace(
            test="f_test",
            formula="p = 1 - F.cdf(F, df1, df2)",
            inputs={"F": claim.statistic, "df1": claim.df1, "df2": claim.df2},
            substitution=f"p = 1 - F.cdf({claim.statistic:g}, {claim.df1}, {claim.df2})",
            result=result,
        )

    if claim.kind == "chi_square":
        if claim.df1 is None:
            raise ValueError("chi-square claim is missing degrees of freedom")
        result = float(stats.chi2.sf(claim.statistic, claim.df1))
        return MathTrace(
            test="chi_square_test",
            formula="p = 1 - chi2.cdf(X2, df)",
            inputs={"X2": claim.statistic, "df": claim.df1},
            substitution=f"p = 1 - chi2.cdf({claim.statistic:g}, {claim.df1})",
            result=result,
        )

    if claim.kind == "r":
        if claim.df1 is None:
            raise ValueError("r claim is missing degrees of freedom")
        r = claim.statistic
        if abs(r) >= 1:
            result = 0.0
            t_value = math.inf
        else:
            t_value = r * math.sqrt(claim.df1 / (1 - r**2))
            result = float(stats.t.sf(abs(t_value), claim.df1) * 2)
        return MathTrace(
            test="pearson_correlation_t_test",
            formula="t = r * sqrt(df / (1 - r^2)); p = 2 * (1 - t.cdf(abs(t), df))",
            inputs={"r": claim.statistic, "df": claim.df1, "t": t_value},
            substitution=f"t = {r:g} * sqrt({claim.df1} / (1 - {r:g}^2)); p = 2 * (1 - t.cdf({abs(t_value):g}, {claim.df1}))",
            result=result,
        )

    raise ValueError(f"Unsupported statistic kind: {claim.kind}")


def classify_claim(claim: StatisticalClaim, recomputed_p: float, tolerance: float) -> tuple[str, str]:
    reported = claim.reported_p

    if claim.comparator == "=":
        diff = abs(reported - recomputed_p)
        if diff <= tolerance:
            return "ok", f"Reported p matches recomputed p within +/- {tolerance:g}."
        return "mismatch", "Reported p-value does not match the recomputed p-value."

    if claim.comparator == "<":
        if recomputed_p < reported:
            return "ok", "Recomputed p satisfies the reported threshold."
        return "mismatch", "Reported p-value does not match the recomputed p-value; the recomputed value does not satisfy the reported '<' threshold."

    if claim.comparator == ">":
        if recomputed_p > reported:
            return "ok", "Recomputed p satisfies the reported threshold."
        return "mismatch", "Reported p-value does not match the recomputed p-value; the recomputed value does not satisfy the reported '>' threshold."

    return "unknown", "Unsupported p-value comparator."


def _confidence_for(evidence: EvidenceTrace, math_trace: MathTrace) -> str:
    has_inputs = bool(math_trace.inputs)
    has_quote = bool(evidence.quote and evidence.exact_quote)
    if has_inputs and has_quote and evidence.page is not None and bool(evidence.bboxes):
        return "High"
    if has_inputs and has_quote:
        return "Medium"
    return "Low"


def _evidence_for_claim(
    text: str,
    claim: StatisticalClaim,
    page_spans: list[PageSpan] | None = None,
) -> EvidenceTrace:
    page_number = None
    claim_bboxes: list[dict[str, float]] = []
    active_span: PageSpan | None = None
    for span in page_spans or []:
        if span.start_char <= claim.start_char <= span.end_char:
            page_number = span.page
            active_span = span
            claim_bboxes = span.bboxes_by_quote.get((claim.start_char, claim.end_char), [])
            break
    quote, quote_start, quote_end, surrounding = _sentence_context(text, claim.start_char, claim.end_char)
    sentence_bboxes = [
        word.bbox for word in (active_span.word_spans if active_span else [])
        if word.end_char > quote_start and word.start_char < quote_end
    ]
    bboxes = _merge_boxes_by_line(sentence_bboxes) if sentence_bboxes else claim_bboxes
    return EvidenceTrace(
        page=page_number,
        section=_section_for_offset(text, claim.start_char),
        quote=quote or claim.raw,
        start_char=claim.start_char,
        end_char=claim.end_char,
        exact_quote=claim.raw,
        quote_start_char=quote_start,
        quote_end_char=quote_end,
        surrounding_context=surrounding or quote or claim.raw,
        bbox=bboxes[0] if bboxes else None,
        bboxes=bboxes,
    )


def audit_text(
    text: str,
    tolerance: float = DEFAULT_TOLERANCE,
    page_spans: list[PageSpan] | None = None,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for claim in extract_claims(text):
        math_trace = recompute_math_trace(claim)
        status, message = classify_claim(claim, math_trace.result, tolerance)
        evidence = _evidence_for_claim(text, claim, page_spans)
        findings.append(
            AuditFinding(
                status=status,
                claim=claim.raw,
                reported_p=_format_reported_p(claim),
                recomputed_p=math_trace.result,
                difference=abs(claim.reported_p - math_trace.result),
                confidence=_confidence_for(evidence, math_trace),
                evidence=evidence,
                math=math_trace,
                note=message,
            )
        )
    return findings


def audit_pdf(path: str | Path, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    text, page_spans = _extract_pdf_with_trace(path)
    findings = audit_text(text, tolerance, page_spans)
    return {
        "source": str(path),
        "claim_count": len(findings),
        "mismatch_count": sum(1 for finding in findings if finding.status == "mismatch"),
        "findings": [finding.to_dict() for finding in findings],
    }


def audit_pdf_bytes(data: bytes, source: str = "uploaded PDF", tolerance: float = DEFAULT_TOLERANCE) -> dict:
    text, page_spans = _extract_pdf_with_trace(data)
    findings = audit_text(text, tolerance, page_spans)
    return {
        "source": source,
        "claim_count": len(findings),
        "mismatch_count": sum(1 for finding in findings if finding.status == "mismatch"),
        "findings": [finding.to_dict() for finding in findings],
    }


def write_json_report(result: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(result, indent=2), encoding="utf-8")


def write_markdown_report(result: dict, path: str | Path) -> None:
    lines = [
        "# Statistical Audit Report",
        "",
        f"Source: `{result['source']}`",
        f"Claims found: {result['claim_count']}",
        f"Mismatches: {result['mismatch_count']}",
        "",
    ]
    for index, finding in enumerate(result["findings"], start=1):
        evidence = finding["evidence"]
        math_trace = finding["math"]
        inputs = ", ".join(f"{k}={v:.6g}" if isinstance(v, float) else f"{k}={v}" for k, v in math_trace["inputs"].items())
        source_link = f"{result['source']}#page={evidence['page']}" if evidence.get("page") else result["source"]
        is_ok = finding["status"] == "ok"
        status_label = "OK" if is_ok else ("Mismatch" if finding["status"] == "mismatch" else finding["status"].title())
        details_title = "Verification Details" if is_ok else "Why this was flagged"
        quote = evidence["quote"]
        exact = evidence.get("exact_quote") or finding["claim"]
        highlighted_quote = quote.replace(exact, f"**{exact}**", 1) if exact in quote else quote
        lines.extend(
            [
                f"## Finding {index}: {status_label}",
                "",
                f"**Claim:** `{finding['claim']}`",
                "",
                f"**Source quote:** [\"{highlighted_quote}\"]({source_link})",
                "",
                f"**Reported p:** `{finding['reported_p']}`",
                "",
                "<details>",
                f"<summary>{details_title}</summary>",
                "",
                f"**Test:** `{math_trace['test']}`",
                "",
                f"**Formula:** `{math_trace['formula']}`",
                "",
                f"**Inputs:** `{inputs}`",
                "",
                f"**Substitution:** `{math_trace['substitution']}`",
                "",
                f"**Computed:** `p={finding['recomputed_p']:.6g}`",
                "",
                f"**Compare:** reported `{finding['reported_p']}`, computed `p={finding['recomputed_p']:.6g}`",
                "",
                f"**Difference:** `{finding.get('difference', 0):.6g}`",
                "",
                f"**Confidence:** {finding.get('confidence', 'Medium')}",
                "",
                f"**Verdict:** {status_label}",
                "",
                "</details>",
                "",
                f"**Result:** {finding['note']}",
                "",
            ]
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html_report(result: dict, path: str | Path) -> None:
    rows = []
    for index, finding in enumerate(result["findings"], start=1):
        evidence = finding["evidence"]
        math_trace = finding["math"]
        inputs = ", ".join(
            f"{html.escape(str(k))}={v:.6g}" if isinstance(v, float) else f"{html.escape(str(k))}={html.escape(str(v))}"
            for k, v in math_trace["inputs"].items()
        )
        page = str(evidence["page"]) if evidence.get("page") else "unavailable"
        quote_href = f"{html.escape(result['source'])}#page={evidence['page']}" if evidence.get("page") else "#"
        is_ok = finding["status"] == "ok"
        status_label = "OK" if is_ok else ("Mismatch" if finding["status"] == "mismatch" else finding["status"].title())
        details_title = "Verification Details" if is_ok else "Why this was flagged"
        quote = evidence["quote"]
        exact = evidence.get("exact_quote") or finding["claim"]
        if exact and exact in quote:
            start, end = quote.split(exact, 1)
            highlighted_quote = f"{html.escape(start)}<mark>{html.escape(exact)}</mark>{html.escape(end)}"
        else:
            highlighted_quote = html.escape(quote)
        rows.append(
            f"""<tr class="{html.escape(finding['status'])}">
      <td><strong>{html.escape(status_label)}</strong></td>
      <td><code>{html.escape(finding['claim'])}</code></td>
      <td>{html.escape(page)}</td>
      <td><a href="{quote_href}">&ldquo;{html.escape(evidence['quote'])}&rdquo;</a></td>
      <td><code>{finding['recomputed_p']:.6g}</code></td>
      <td>{html.escape(finding['note'])}</td>
    </tr>
    <tr class="details-row">
      <td colspan="6">
        <details>
          <summary>{html.escape(details_title)}</summary>
          <div class="detail-grid">
            <div>
              <h3>Evidence</h3>
              <blockquote>&ldquo;{highlighted_quote}&rdquo;</blockquote>
            </div>
            <div>
              <h3>Math</h3>
              <dl>
                <dt>Test</dt><dd><code>{html.escape(math_trace['test'])}</code></dd>
                <dt>Formula</dt><dd><code>{html.escape(math_trace['formula'])}</code></dd>
                <dt>Inputs</dt><dd><code>{inputs}</code></dd>
                <dt>Substitution</dt><dd><code>{html.escape(math_trace['substitution'])}</code></dd>
                <dt>Computed</dt><dd><code>p={finding['recomputed_p']:.6g}</code></dd>
                <dt>Compare</dt><dd>reported <code>{html.escape(finding['reported_p'])}</code>, computed <code>p={finding['recomputed_p']:.6g}</code></dd>
                <dt>Difference</dt><dd><code>{float(finding.get('difference', 0)):.6g}</code></dd>
                <dt>Confidence</dt><dd>{html.escape(finding.get('confidence', 'Medium'))}</dd>
                <dt>Verdict</dt><dd>{html.escape(status_label)}</dd>
              </dl>
            </div>
          </div>
        </details>
      </td>
    </tr>"""
        )

    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Statistical Audit Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.45; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 0.65rem; vertical-align: top; text-align: left; }}
    th {{ background: #f9fafb; font-size: 0.85rem; color: #374151; }}
    tr.mismatch > td:first-child {{ color: #b91c1c; }}
    tr.ok > td:first-child {{ color: #047857; }}
    .details-row td {{ background: #fbfbfb; padding: 0.5rem 1rem 1rem; }}
    .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-top: 0.75rem; }}
    dl {{ display: grid; grid-template-columns: 8rem 1fr; gap: 0.45rem 1rem; }}
    dt {{ font-weight: 700; color: #374151; }}
    dd {{ margin: 0; }}
    code {{ white-space: normal; background: #f3f4f6; padding: 0.1rem 0.25rem; border-radius: 4px; }}
    mark {{ background: #fef08a; padding: 0.05rem 0.2rem; border-radius: 3px; }}
    blockquote {{ border-left: 3px solid #d1d5db; margin: 0; padding-left: 0.75rem; color: #4b5563; }}
    a {{ color: #1d4ed8; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    @media (max-width: 800px) {{ .detail-grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>Statistical Audit Report</h1>
  <p><strong>Source:</strong> <code>{html.escape(result['source'])}</code></p>
  <p><strong>Claims found:</strong> {result['claim_count']}<br>
  <strong>Mismatches:</strong> {result['mismatch_count']}</p>
  <table>
    <thead>
      <tr><th>Status</th><th>Claim</th><th>Page</th><th>Source Quote</th><th>Computed p</th><th>Verdict</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    Path(path).write_text(body, encoding="utf-8")
