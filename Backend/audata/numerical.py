"""Numerical consistency agent for AuData (server-side, unified).

One model call (via the task-aware router) checks the paper's internal numbers
across categories and returns a single flat list of flags plus a per-category
summary, so the UI can present every numerical-consistency check in one place:

  • n_sum_error            subgroup Ns should sum to the total
  • percentage_mismatch    count / total * 100 should match the reported %
  • table_text_discrepancy the same number should agree between tables and prose
  • implausible_value      means / SDs / ranges that are statistically impossible
  • abstract_results       abstract numbers should match the results section
  • qualitative_quantifier "majority/most/few" should agree with the actual %
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import llm

CATEGORIES = [
    ("n_sum_error", "Subgroup N sums"),
    ("percentage_mismatch", "Percentage vs counts"),
    ("table_text_discrepancy", "Table vs prose"),
    ("implausible_value", "Implausible values"),
    ("abstract_results", "Abstract vs results"),
    ("qualitative_quantifier", "Qualitative quantifiers"),
]

_PROMPT = """You are a biomedical research-integrity auditor. Check the paper's internal numerical consistency across SIX categories. For EVERY category write a one-line summary of what you actually found (name the real numbers), even if everything checks out.

Categories:
- n_sum_error: do subgroup Ns add up to the stated total?
- percentage_mismatch: does count / total * 100 match the reported percentage?
- table_text_discrepancy: do the same numbers agree between tables and the body text?
- implausible_value: are any means, SDs, ranges, or percentages statistically impossible (e.g. >100%, SD larger than the range allows)?
- abstract_results: do numbers in the abstract match the results section?
- qualitative_quantifier: does a word like "majority/most/nearly all/few/minority" agree with the actual percentage in the paper?

Return ONLY valid JSON:
{
  "summaries": { "n_sum_error": "...", "percentage_mismatch": "...", "table_text_discrepancy": "...", "implausible_value": "...", "abstract_results": "...", "qualitative_quantifier": "..." },
  "flags": [
    {"type": "<one of the six category keys>", "severity": "high"|"medium"|"low", "description": "name BOTH conflicting values explicitly", "excerpt": "verbatim quote <= 160 chars"}
  ]
}
If a category has nothing to check, say so in its summary. flags may be empty.

PAPER:
<paper>
{body}
</paper>
JSON:"""

_VALID_TYPES = {k for k, _ in CATEGORIES}


def analyze(paper: Dict[str, Any], model) -> Dict[str, Any]:
    if model is None:
        return {"flags": [], "summaries": {}, "summary": _summary([]), "note": "No model is configured."}
    body = (paper.get("full_text") or paper.get("abstract") or "")[:30000]
    if not body.strip():
        return {"flags": [], "summaries": {}, "summary": _summary([]), "note": "No full text to check."}
    raw = llm.invoke(model, _PROMPT.replace("{body}", body))
    data = llm.extract_json(raw)
    flags: List[Dict[str, Any]] = []
    summaries: Dict[str, str] = {}
    if isinstance(data, dict):
        for f in (data.get("flags") or []):
            if not isinstance(f, dict):
                continue
            t = str(f.get("type", "other")).strip()
            sev = str(f.get("severity", "medium")).strip().lower()
            if sev not in ("high", "medium", "low"):
                sev = "medium"
            flags.append({
                "type": t if t in _VALID_TYPES else "other",
                "severity": sev,
                "description": str(f.get("description", "")).strip(),
                "excerpt": str(f.get("excerpt", "")).strip(),
            })
        s = data.get("summaries")
        if isinstance(s, dict):
            summaries = {str(k): str(v) for k, v in s.items()}
    return {"flags": flags, "summaries": summaries, "summary": _summary(flags)}


def _summary(flags: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_sev: Dict[str, int] = {}
    for f in flags:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    return {"checked": len(CATEGORIES), "flagged": len(flags), "by_severity": by_sev}
