"""Meta-analysis recreation for AuData.

If the paper under audit is a meta-analysis, re-extract each included study's
effect size (or 2x2 counts) and recompute the pooled effect with inverse-variance
fixed-effect and DerSimonian-Laird random-effects models, plus heterogeneity
(Q, I^2, tau^2). Compare the recomputed pooled estimate to the paper's reported
pooled estimate and flag material discrepancies. Returns forest-plot data too.

Deterministic math; an LLM only does the extraction step.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import llm

Z95 = 1.959963984540054

_RATIO = {"or", "rr", "hr", "odds ratio", "risk ratio", "hazard ratio", "ratio"}


def _is_ratio(measure: str) -> bool:
    return (measure or "").strip().lower() in _RATIO


def _study_effect(s: Dict[str, Any], measure: str):
    """Return (y, se) on the analysis scale (log scale for ratio measures)."""
    ratio = _is_ratio(measure)
    et, nt, ec, nc = s.get("events_t"), s.get("n_t"), s.get("events_c"), s.get("n_c")
    if None not in (et, nt, ec, nc):
        try:
            a, n1, c, n2 = float(et), float(nt), float(ec), float(nc)
        except (TypeError, ValueError):
            a = None
        if a is not None and n1 > 0 and n2 > 0:
            b, d = n1 - a, n2 - c
            if min(a, b, c, d) == 0:                # Haldane-Anscombe correction
                a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            ml = (measure or "or").strip().lower()
            if ml in ("rr", "risk ratio"):
                y = math.log((a / (a + b)) / (c / (c + d)))
                se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
            else:                                   # odds ratio
                y = math.log((a * d) / (b * c))
                se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
            return y, se
    eff, lo, hi = s.get("effect"), s.get("ci_low"), s.get("ci_high")
    try:
        eff, lo, hi = float(eff), float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if ratio:
        if min(eff, lo, hi) <= 0:
            return None
        y = math.log(eff)
        se = (math.log(hi) - math.log(lo)) / (2 * Z95)
    else:
        y = eff
        se = (hi - lo) / (2 * Z95)
    return (y, se) if se > 0 else None


def _pool(ys: List[float], ses: List[float], model: str) -> Dict[str, Any]:
    """Pool effects; return the estimate plus every intermediate value so the
    calculation can be audited step by step."""
    w = [1.0 / (se * se) for se in ses]
    sw = sum(w)
    ybar = sum(wi * yi for wi, yi in zip(w, ys)) / sw
    Q = sum(wi * (yi - ybar) ** 2 for wi, yi in zip(w, ys))
    k = len(ys)
    df = k - 1
    i2 = max(0.0, (Q - df) / Q) * 100 if Q > 0 and df > 0 else 0.0
    out = {"w": w, "sw": sw, "ybar": ybar, "Q": Q, "df": df, "i2": i2, "tau2": 0.0}
    if model == "random" and df > 0:
        c = sw - sum(wi * wi for wi in w) / sw
        tau2 = max(0.0, (Q - df) / c) if c > 0 else 0.0
        wr = [1.0 / (se * se + tau2) for se in ses]
        swr = sum(wr)
        out.update(tau2=tau2, c=c, wr=wr, swr=swr,
                   est=sum(wi * yi for wi, yi in zip(wr, ys)) / swr,
                   se_p=math.sqrt(1.0 / swr),
                   weights=[wi / swr for wi in wr])
    else:
        out.update(est=ybar, se_p=math.sqrt(1.0 / sw), weights=[wi / sw for wi in w])
    return out


def compute(studies: List[Dict[str, Any]], measure: str, model: str) -> Optional[Dict[str, Any]]:
    ratio = _is_ratio(measure)
    ys: List[float] = []
    ses: List[float] = []
    kept: List[Dict[str, Any]] = []
    for s in studies:
        r = _study_effect(s, measure)
        if r:
            ys.append(r[0]); ses.append(r[1]); kept.append(s)
    if len(ys) < 2:
        return None
    model = "fixed" if (model or "").strip().lower().startswith("fix") else "random"
    p = _pool(ys, ses, model)
    est, se_p = p["est"], p["se_p"]
    lo, hi = est - Z95 * se_p, est + Z95 * se_p
    back = (lambda v: math.exp(v)) if ratio else (lambda v: v)
    scale = "log scale" if ratio else "raw scale"

    forest = []
    for s, y, se, wgt in zip(kept, ys, ses, p["weights"]):
        forest.append({
            "label": s.get("label") or "Study",
            "effect": round(back(y), 4),
            "ci_low": round(back(y - Z95 * se), 4),
            "ci_high": round(back(y + Z95 * se), 4),
            "weight": round(wgt * 100, 1),
            "y": round(y, 4), "se": round(se, 4),
        })

    f = lambda v: round(v, 4)
    steps: List[Dict[str, str]] = []
    if ratio:
        steps.append({"label": "1. Put each study on the log scale",
                      "formula": "y = ln(effect),  SE = (ln(CI_high) − ln(CI_low)) / (2 × 1.96)",
                      "value": f"Ratio measure ({measure}); pooling is done on the {scale}, then exponentiated."})
    else:
        steps.append({"label": "1. Per-study standard error from the CI",
                      "formula": "SE = (CI_high − CI_low) / (2 × 1.96)",
                      "value": f"Difference measure ({measure}); pooling on the {scale}."})
    steps.append({"label": "2. Inverse-variance weights",
                  "formula": "wᵢ = 1 / SEᵢ²",
                  "value": f"Σw = {f(p['sw'])}  (k = {len(ys)} studies)"})
    steps.append({"label": "3. Fixed-effect weighted mean",
                  "formula": "ȳ = Σ(wᵢ·yᵢ) / Σwᵢ",
                  "value": f"ȳ = {f(p['ybar'])} ({scale})"})
    steps.append({"label": "4. Heterogeneity (Cochran's Q)",
                  "formula": "Q = Σ wᵢ(yᵢ − ȳ)²,  df = k − 1",
                  "value": f"Q = {f(p['Q'])}, df = {p['df']}"})
    steps.append({"label": "5. I² statistic",
                  "formula": "I² = max(0, (Q − df) / Q)",
                  "value": f"I² = {round(p['i2'], 1)}%"})
    if model == "random":
        steps.append({"label": "6. Between-study variance τ² (DerSimonian–Laird)",
                      "formula": "τ² = max(0, (Q − df) / C),  C = Σw − Σw²/Σw",
                      "value": f"C = {f(p.get('c', 0.0))}, τ² = {f(p['tau2'])}"})
        steps.append({"label": "7. Random-effects weights",
                      "formula": "wᵢ* = 1 / (SEᵢ² + τ²)",
                      "value": f"Σw* = {f(p.get('swr', 0.0))}"})
        steps.append({"label": "8. Random-effects pooled estimate",
                      "formula": "ŷ = Σ(wᵢ*·yᵢ) / Σwᵢ*,  SE = √(1/Σwᵢ*)",
                      "value": f"ŷ = {f(est)}, SE = {f(se_p)} ({scale})"})
    else:
        steps.append({"label": "6. Fixed-effect pooled estimate",
                      "formula": "ŷ = ȳ,  SE = √(1/Σwᵢ)",
                      "value": f"ŷ = {f(est)}, SE = {f(se_p)} ({scale})"})
    steps.append({"label": f"{9 if model == 'random' else 7}. 95% confidence interval",
                  "formula": "ŷ ± 1.96 × SE",
                  "value": f"[{f(lo)}, {f(hi)}] ({scale})"})
    if ratio:
        steps.append({"label": f"{10 if model == 'random' else 8}. Back-transform to the {measure} scale",
                      "formula": "effect = exp(ŷ);  CI = [exp(low), exp(high)]",
                      "value": f"{measure} = {round(back(est), 3)}  [{round(back(lo), 3)}, {round(back(hi), 3)}]"})

    return {
        "model": model, "measure": measure, "ratio": ratio, "k": len(ys),
        "pooled": {"effect": round(back(est), 4), "ci_low": round(back(lo), 4), "ci_high": round(back(hi), 4)},
        "i2": round(p["i2"], 1), "q": round(p["Q"], 3), "tau2": round(p["tau2"], 4),
        "forest": forest, "steps": steps,
    }


_EXTRACT_PROMPT = """You are extracting a meta-analysis from a research paper so its pooled effect can be recomputed.

Return ONLY JSON:
{
  "is_meta_analysis": true|false,
  "measure": "OR" | "RR" | "HR" | "MD" | "SMD" | "",   // effect measure of the main pooled analysis
  "model": "random" | "fixed" | "",
  "reported_pooled": { "effect": <num>, "ci_low": <num>, "ci_high": <num> },  // the paper's headline pooled estimate
  "reported_i2": <num or null>,
  "studies": [
    // ONE object per included study in the MAIN forest plot. Prefer effect+CI; use 2x2 counts only if effect/CI are absent.
    { "label": "First author year", "effect": <num>, "ci_low": <num>, "ci_high": <num>,
      "events_t": <num or null>, "n_t": <num or null>, "events_c": <num or null>, "n_c": <num or null> }
  ]
}

Rules:
- If the paper is not a meta-analysis with a pooled effect, return {"is_meta_analysis": false, "studies": []}.
- Use the single main/primary pooled analysis (largest forest plot), not subgroups.
- Numbers only (no % signs, no CI text). For ratio measures keep them on the natural scale (e.g. OR 1.45, CI 1.10-1.92).

PAPER TEXT:
---
{body}
---
JSON:"""


def extract_meta(paper: Dict[str, Any], model) -> Dict[str, Any]:
    if model is None:
        return {"is_meta_analysis": False, "studies": []}
    body = (paper.get("full_text") or paper.get("abstract") or "")[:28000]
    if not body.strip():
        return {"is_meta_analysis": False, "studies": []}
    raw = llm.invoke(model, _EXTRACT_PROMPT.replace("{body}", body))
    data = llm.extract_json(raw)
    if not isinstance(data, dict):
        return {"is_meta_analysis": False, "studies": []}
    data.setdefault("studies", [])
    if not isinstance(data["studies"], list):
        data["studies"] = []
    return data


def analyze(paper: Dict[str, Any], model) -> Dict[str, Any]:
    meta = extract_meta(paper, model)
    if not meta.get("is_meta_analysis"):
        return {"detected": False, "note": "No meta-analysis with a pooled effect was detected in this paper."}
    measure = meta.get("measure") or "OR"
    mdl = meta.get("model") or "random"
    recomputed = compute(meta.get("studies", []), measure, mdl)
    reported = meta.get("reported_pooled") or {}
    out: Dict[str, Any] = {
        "detected": True, "measure": measure, "model": mdl,
        "reported": reported, "reported_i2": meta.get("reported_i2"),
        "recomputed": recomputed,
        "verdict": "unknown", "severity": "info", "explanation": "",
    }
    if not recomputed:
        out["explanation"] = "Could not recompute: fewer than two usable study effect sizes were extracted."
        return out

    rec_eff = recomputed["pooled"]["effect"]
    rep_eff = reported.get("effect")
    try:
        rep_eff = float(rep_eff)
    except (TypeError, ValueError):
        rep_eff = None
    if rep_eff is None:
        out.update(verdict="recomputed", severity="info",
                   explanation=f"Recomputed pooled {measure} = {rec_eff} "
                               f"[{recomputed['pooled']['ci_low']}, {recomputed['pooled']['ci_high']}] "
                               f"from {recomputed['k']} studies. No reported pooled value to compare.")
        return out

    ratio = recomputed["ratio"]
    if ratio and rep_eff > 0 and rec_eff > 0:
        rel = abs(math.log(rec_eff) - math.log(rep_eff))
        scale = "log-ratio"
    else:
        denom = abs(rep_eff) if rep_eff else 1.0
        rel = abs(rec_eff - rep_eff) / denom
        scale = "relative"
    # reported point inside recomputed CI?
    inside = recomputed["pooled"]["ci_low"] <= rep_eff <= recomputed["pooled"]["ci_high"]
    if rel <= 0.05 or inside:
        out.update(verdict="consistent", severity="none",
                   explanation=f"Recomputed pooled {measure} = {rec_eff} "
                               f"[{recomputed['pooled']['ci_low']}, {recomputed['pooled']['ci_high']}] "
                               f"matches the reported {rep_eff} ({recomputed['k']} studies, I^2={recomputed['i2']}%).")
    else:
        sev = "high" if rel > 0.15 else "medium"
        out.update(verdict="discrepancy", severity=sev,
                   explanation=f"Recomputed pooled {measure} = {rec_eff} "
                               f"[{recomputed['pooled']['ci_low']}, {recomputed['pooled']['ci_high']}] "
                               f"differs from the reported {rep_eff} ({scale} difference {round(rel, 3)}; "
                               f"{recomputed['k']} studies). Check the extracted study data or the pooling.")
    return out
