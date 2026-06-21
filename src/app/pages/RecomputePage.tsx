import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FileInput, FileSearch, Loader2, Play, XCircle } from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Checkbox } from "../components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { useStore } from "../lib/store";
import {
  StatisticalAuditService, MetaRecreateService, AuditStore, apiConfig,
  type StatisticalFinding, type StatisticalRecomputeResult,
  type MetaAnalysisResult, type MetaRecomputed,
} from "../lib/apiClient";

function fmtP(value: number) {
  if (!Number.isFinite(value)) return "n/a";
  if (value < 0.0001) return value.toExponential(2);
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function fmtInputs(inputs: Record<string, number>) {
  return Object.entries(inputs)
    .map(([key, value]) => `${key}=${fmtP(value)}`)
    .join(", ");
}

function prettyTest(name: string) {
  return name.replace(/_/g, " ");
}

function statusLabel(status: StatisticalFinding["status"]) {
  if (status === "ok") return "OK";
  if (status === "mismatch") return "Mismatch";
  return "Unknown";
}

function HighlightedQuote({ quote, match }: { quote: string; match: string }) {
  const index = quote.indexOf(match);
  if (!match || index < 0) return <>{quote}</>;
  return (
    <>
      {quote.slice(0, index)}
      <mark className="rounded bg-yellow-200 px-1 text-foreground">{match}</mark>
      {quote.slice(index + match.length)}
    </>
  );
}

function ClaimText({ claim }: { claim: string }) {
  const match = claim.match(/^(.*?,\s*)(p\s*[<>=]\s*.+)$/i);
  if (!match) return <>{claim}</>;
  const pPart = match[2].replace(/\s+/g, " ");
  return (
    <>
      {match[1]}
      <span className="whitespace-nowrap">{pPart}</span>
    </>
  );
}

// Build the URL for the server-highlighted PDF: it burns in the exact bounding
// boxes for this finding and embeds an /OpenAction so the viewer jumps straight
// to the highlighted statistic.
function pdfHref(paperId: string, finding: StatisticalFinding) {
  const page = finding.evidence.page || 1;
  const boxes = encodeURIComponent(JSON.stringify(finding.evidence.bboxes || []));
  const firstBox = finding.evidence.bboxes?.[0];
  const left = Math.max(0, Math.floor((firstBox?.x0 || 0) - 40));
  const top = Math.max(0, Math.floor((firstBox?.y0 || 0) - 90));
  const frag = firstBox ? `page=${page}&zoom=150,${left},${top}` : `page=${page}`;
  return `${apiConfig.baseUrl}/audit/pdf-highlight?id=${encodeURIComponent(paperId)}&page=${page}&boxes=${boxes}#${frag}`;
}

export function RecomputePage() {
  const store = useStore();
  const paper = store.paperUnderAudit;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<StatisticalRecomputeResult | null>(null);
  const [mismatchOnly, setMismatchOnly] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [locateOpen, setLocateOpen] = useState(false);
  const [view, setView] = useState<"stats" | "meta">("stats");
  const auditKey = paper?.id || "__none__";

  // Reset only when the paper changes (and has no saved result) — never on a
  // transient store change, so results don't vanish.
  useEffect(() => {
    if (store.statcheckAudits?.[auditKey]) return;
    setResult(null); setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  // Apply the saved recompute from the store (reactive to Dashboard "Run all"),
  // surviving tab switches and refresh; pull from the server once if absent.
  useEffect(() => {
    let cancelled = false;
    const local = store.statcheckAudits?.[auditKey] as StatisticalRecomputeResult | undefined;
    if (local) {
      setResult(local);
      setSelected((cur) => {
        const n = local.findings?.length || 0;
        if (cur != null && cur < n) return cur;
        const fm = local.findings?.findIndex((f) => f.status === "mismatch") ?? -1;
        return n ? (fm >= 0 ? fm : 0) : null;
      });
    } else if (paper) {
      AuditStore.getAll(paper.id).then((a) => {
        if (cancelled || !a.statcheck) return;
        store.setStatcheckAudits({ ...store.statcheckAudits, [auditKey]: a.statcheck });
      });
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey, store.statcheckAudits?.[auditKey]]);

  async function runAudit() {
    if (!paper) return;
    setBusy(true); setError(""); setSelected(null);
    try {
      const r = await StatisticalAuditService.recompute(paper);
      setResult(r);
      const firstMismatch = r.findings.findIndex((f) => f.status === "mismatch");
      setSelected(r.findings.length ? (firstMismatch >= 0 ? firstMismatch : 0) : null);
      AuditStore.save(paper.id, "statcheck", r);   // surface in the Audit Report
      store.setStatcheckAudits({ ...store.statcheckAudits, [paper.id]: r });
    } catch (e: any) {
      setError(e?.message || "Statistical recompute failed.");
    } finally {
      setBusy(false);
    }
  }

  const findings = result?.findings ?? [];
  const shown = useMemo(
    () => findings.map((f, i) => ({ f, i })).filter(({ f }) => !mismatchOnly || f.status === "mismatch"),
    [findings, mismatchOnly],
  );
  const sel = selected != null ? findings[selected] : null;

  if (!paper) {
    return (
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-md bg-muted p-3"><FileInput className="size-5 text-muted-foreground" /></div>
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">No paper loaded</h2>
              <p className="text-sm text-muted-foreground">Upload or fetch a paper in Ingest first.</p>
            </div>
            <Button onClick={() => store.setPage("ingest")} variant="outline">Open Ingest</Button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-lg border bg-muted/40 p-0.5 text-sm">
        <button onClick={() => setView("stats")}
          className={`rounded-md px-3 py-1.5 font-medium transition-colors ${view === "stats" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          Statistical recompute
        </button>
        <button onClick={() => setView("meta")}
          className={`rounded-md px-3 py-1.5 font-medium transition-colors ${view === "meta" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          Meta-analysis
        </button>
      </div>

      {view === "stats" && (
      <div className="space-y-4">
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button onClick={runAudit} disabled={busy || !paper.full_text} size="sm" className="shrink-0">
            {busy ? <Loader2 className="mr-1.5 size-4 animate-spin" /> : <Play className="mr-1.5 size-4" />}
            {busy ? "Running…" : result ? "Re-run" : "Run"}
          </Button>
          {result && (
            <>
              <Stat label="Claims" value={result.claim_count} />
              <Stat label="Mismatches" value={result.mismatch_count} tone={result.mismatch_count ? "red" : "green"} />
              <Stat label="Consistent" value={Math.max(0, result.claim_count - result.mismatch_count)} tone="green" />
            </>
          )}
          <span className="hidden text-xs text-muted-foreground lg:inline">Supports t, F, chi-square, r</span>
          <div className="flex-1" />
          {findings.length > 0 && (
            <label className="flex cursor-pointer items-center gap-2 text-[11px] text-muted-foreground">
              <Checkbox checked={mismatchOnly} onCheckedChange={(v) => setMismatchOnly(v === true)} />Mismatches only
            </label>
          )}
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        {!paper.full_text && <p className="mt-2 text-xs text-amber-600">This paper has no extracted full text, so statistics cannot be recomputed.</p>}
      </Card>

      {findings.length > 0 && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[340px_1fr]">
          <Card className="self-start p-2">
            <div className="max-h-[640px] space-y-0.5 overflow-y-auto">
              {shown.map(({ f, i }) => {
                const active = i === selected;
                const mismatch = f.status === "mismatch";
                return (
                  <button key={i} onClick={() => setSelected(i)}
                    className={`flex w-full items-start gap-2 rounded px-2 py-1.5 text-left transition-colors ${active ? "border border-primary/30 bg-primary/10" : "border border-transparent hover:bg-muted"}`}>
                    <span className={`mt-1 size-2 shrink-0 rounded-full ${mismatch ? "bg-red-500" : "bg-emerald-500"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium leading-tight text-foreground"><ClaimText claim={f.claim} /></span>
                      <span className={`text-[11px] ${mismatch ? "text-red-600" : "text-emerald-600"}`}>{statusLabel(f.status)}</span>
                    </span>
                  </button>
                );
              })}
              {shown.length === 0 && <div className="p-3 text-center text-xs text-muted-foreground">No matching findings.</div>}
            </div>
          </Card>

          <Card className="min-h-[300px] self-start p-5">
            {sel ? <FindingDetail finding={sel} canLocate={!!paper.has_pdf} onLocate={() => setLocateOpen(true)} />
              : <div className="text-sm text-muted-foreground">Select a finding on the left.</div>}
          </Card>
        </div>
      )}

      <Dialog open={locateOpen} onOpenChange={setLocateOpen}>
        <DialogContent className="w-[97vw] max-w-[min(1500px,97vw)] sm:max-w-[min(1500px,97vw)]">
          <DialogHeader><DialogTitle className="text-sm">Locate in PDF</DialogTitle></DialogHeader>
          {paper.has_pdf && sel && locateOpen && (
            <iframe
              title="Highlighted PDF"
              src={pdfHref(paper.id, sel)}
              className="h-[82vh] w-full rounded border bg-muted/30"
            />
          )}
        </DialogContent>
      </Dialog>

      {result && findings.length === 0 && (
        <Card className="p-8 text-center">
          <div className="font-medium">No supported statistical claims were found.</div>
          <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">
            {result.no_findings_reason || "The extracted text did not contain a supported t, F, chi-square, or r claim paired with a p-value."}
          </p>
        </Card>
      )}

      </div>
      )}

      {view === "meta" && <MetaAnalysisSection />}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "red" | "green" }) {
  const c = tone === "red" ? "text-red-600" : tone === "green" ? "text-emerald-600" : "text-foreground";
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-lg font-semibold ${c}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function FindingDetail({ finding, canLocate, onLocate }: { finding: StatisticalFinding; canLocate?: boolean; onLocate?: () => void }) {
  const mismatch = finding.status === "mismatch";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={mismatch ? "border-red-500/30 bg-red-500/10 text-red-600" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"}>
            {mismatch ? <XCircle className="mr-1 size-3" /> : <CheckCircle2 className="mr-1 size-3" />}{statusLabel(finding.status)}
          </Badge>
          {finding.confidence && <span className="text-[11px] capitalize text-muted-foreground">confidence: {finding.confidence}</span>}
        </div>
        {canLocate && (
          <Button variant="outline" size="sm" onClick={onLocate} title="Highlight in the PDF">
            <FileSearch className="mr-1 size-3.5" />Locate in PDF
          </Button>
        )}
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">Reported claim</div>
        <p className="text-[15px] font-semibold tracking-tight"><ClaimText claim={finding.claim} /></p>
      </div>

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">Source quote</div>
        <blockquote className="border-l-2 border-muted pl-3 text-sm text-muted-foreground">
          <HighlightedQuote quote={finding.evidence.quote} match={finding.evidence.exact_quote} />
        </blockquote>
      </div>

      <div>
        <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">{mismatch ? "Math breakdown" : "Verification"}</div>
        <ol className="space-y-3 text-sm">
          <li>
            <div className="font-medium">1. Test type</div>
            <div className="text-muted-foreground">{prettyTest(finding.math.test)}</div>
          </li>
          <li>
            <div className="font-medium">2. Extract the reported values</div>
            <code className="block rounded-md bg-muted/70 px-2.5 py-1.5 font-mono text-[12.5px] leading-relaxed">{fmtInputs(finding.math.inputs)}</code>
          </li>
          <li>
            <div className="font-medium">3. p-value formula</div>
            <code className="block rounded-md bg-muted/70 px-2.5 py-1.5 font-mono text-[12.5px] leading-relaxed">{finding.math.formula}</code>
          </li>
          <li>
            <div className="font-medium">4. Substitute the values</div>
            <code className="block rounded-md bg-muted/70 px-2.5 py-1.5 font-mono text-[12.5px] leading-relaxed">{finding.math.substitution}</code>
          </li>
          <li>
            <div className="font-medium">5. Recompute and compare</div>
            <div className="text-muted-foreground">Reported <code className="rounded bg-muted/70 px-1 py-0.5 font-mono text-[12px] text-foreground">{finding.reported_p}</code>; recomputed <code className="rounded bg-muted/70 px-1 py-0.5 font-mono text-[12px] text-foreground">p={fmtP(finding.math.result)}</code>.</div>
            {mismatch && <div className="mt-1 text-muted-foreground">Difference <code className="rounded bg-muted/70 px-1 py-0.5 font-mono text-[12px] text-foreground">{fmtP(finding.difference)}</code>.</div>}
          </li>
          <li>
            <div className="font-medium">6. Verdict</div>
            <div className={mismatch ? "text-red-600" : "text-emerald-600"}>{statusLabel(finding.status)}: {finding.note}</div>
          </li>
        </ol>
      </div>
    </div>
  );
}

// Meta-analysis recreation: re-extract the included studies and recompute the
// pooled effect (fixed + random) to check it against the paper's reported value.
function MetaAnalysisSection() {
  const s = useStore();
  const paper = s.paperUnderAudit;
  const auditKey = paper?.id || "__none__";
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<MetaAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Reset only when the paper changes (and has no saved result).
  useEffect(() => {
    if (s.metaAudits[auditKey]) return;
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  // Apply saved meta result from the store (reactive to Dashboard "Run all");
  // pull from the server once if absent. Never clobbers on a transient change.
  useEffect(() => {
    let cancelled = false;
    const local = s.metaAudits[auditKey];
    if (local) setResult(local);
    else if (paper) AuditStore.getAll(paper.id).then((au) => {
      if (cancelled || !au.meta) return;
      s.setMetaAudits({ ...s.metaAudits, [auditKey]: au.meta });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey, s.metaAudits[auditKey]]);

  async function run() {
    if (!paper) { setError("Ingest a paper first."); return; }
    setError(null); setResult(null); setRunning(true);
    try {
      const out = await MetaRecreateService.checkPaper(paper.id);
      setResult(out);
      s.setMetaAudits({ ...s.metaAudits, [auditKey]: out });
      if (auditKey !== "__none__") AuditStore.save(auditKey, "meta", out);
    } catch (e: any) { setError(e?.message || "Meta-analysis recreation failed."); }
    finally { setRunning(false); }
  }

  const rc = result?.recomputed || null;
  const verdictStyle = result?.verdict === "discrepancy"
    ? "border-red-500/30 bg-red-500/10 text-red-600"
    : result?.verdict === "consistent"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600"
      : "border-slate-500/30 bg-slate-500/10 text-slate-600";
  const verdictLabel = result?.verdict === "discrepancy" ? "Discrepancy"
    : result?.verdict === "consistent" ? "Reproduced"
      : result?.verdict === "recomputed" ? "Recomputed" : "—";

  return (
    <Card className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button size="sm" variant="outline" onClick={run} disabled={!paper || running} className="shrink-0 gap-2">
          {running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
          {running ? "Recreating…" : result ? "Re-run" : "Recreate meta-analysis"}
        </Button>
        {result?.detected && rc && (
          <span className="text-xs capitalize text-muted-foreground">{result.measure} · {result.model}-effects · {rc.k ?? 0} studies</span>
        )}
        <span className="hidden text-xs text-muted-foreground lg:inline">Inverse-variance fixed + DerSimonian-Laird random effects</span>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && !result.detected && (
        <p className="text-sm text-muted-foreground">{result.note || "No meta-analysis with a pooled effect was detected."}</p>
      )}

      {result?.detected && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className={verdictStyle}>{verdictLabel}</Badge>
            <span className="text-xs capitalize text-muted-foreground">{result.measure} · {result.model}-effects · {rc?.k ?? 0} studies</span>
          </div>
          {result.explanation && <p className="text-sm text-muted-foreground">{result.explanation}</p>}

          {rc && (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <PooledStat label="Reported pooled" effect={result.reported?.effect} lo={result.reported?.ci_low} hi={result.reported?.ci_high} measure={result.measure} />
                <PooledStat label="Recomputed pooled" effect={rc.pooled.effect} lo={rc.pooled.ci_low} hi={rc.pooled.ci_high} measure={result.measure} highlight />
                <div className="rounded-md border p-3">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Heterogeneity</div>
                  <div className="mt-1 text-sm">I² = <span className="font-semibold">{rc.i2}%</span></div>
                  <div className="text-xs text-muted-foreground">Q = {rc.q} · τ² = {rc.tau2}{result.reported_i2 != null ? ` · reported I² ${result.reported_i2}%` : ""}</div>
                </div>
              </div>
              <ForestPlot rc={rc} reported={result.reported} />
              <CalculationAudit rc={rc} />
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// Step-by-step audit of the pooling calculation: the per-study inputs and every
// formula with its substituted intermediate value.
function CalculationAudit({ rc }: { rc: MetaRecomputed }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-md border">
      <button onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium hover:bg-muted/40">
        <span>Audit the calculation ({rc.model}-effects, {rc.k} studies)</span>
        <span className="text-xs text-muted-foreground">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="space-y-4 border-t p-4">
          <div>
            <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Per-study inputs</div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-1.5 pr-3 font-medium">Study</th>
                    <th className="py-1.5 pr-3 font-medium">{rc.measure} [95% CI]</th>
                    <th className="py-1.5 pr-3 font-medium">y ({rc.ratio ? "log" : "raw"})</th>
                    <th className="py-1.5 pr-3 font-medium">SE</th>
                    <th className="py-1.5 pr-3 text-right font-medium">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {rc.forest.map((f, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5 pr-3">{f.label}</td>
                      <td className="py-1.5 pr-3 font-mono">{f.effect} [{f.ci_low}, {f.ci_high}]</td>
                      <td className="py-1.5 pr-3 font-mono">{f.y ?? "—"}</td>
                      <td className="py-1.5 pr-3 font-mono">{f.se ?? "—"}</td>
                      <td className="py-1.5 pr-3 text-right font-mono">{f.weight}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {rc.steps && rc.steps.length > 0 && (
            <div>
              <div className="mb-2 text-[10px] uppercase tracking-wide text-muted-foreground">Pooling steps</div>
              <ol className="space-y-2.5">
                {rc.steps.map((st, i) => (
                  <li key={i} className="text-sm">
                    <div className="font-medium">{st.label}</div>
                    <code className="mt-1 block rounded-md bg-muted/70 px-2.5 py-1.5 font-mono text-[12px] leading-relaxed">{st.formula}</code>
                    <div className="mt-0.5 text-[12px] text-muted-foreground">{st.value}</div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PooledStat({ label, effect, lo, hi, measure, highlight }: {
  label: string; effect?: number; lo?: number; hi?: number; measure?: string; highlight?: boolean;
}) {
  const fmt = (v?: number) => (typeof v === "number" ? v.toFixed(2) : "—");
  return (
    <div className={`rounded-md border p-3 ${highlight ? "border-primary/30 bg-primary/5" : ""}`}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{fmt(effect)}</div>
      <div className="text-xs text-muted-foreground">95% CI [{fmt(lo)}, {fmt(hi)}] {measure}</div>
    </div>
  );
}

// Simple forest plot. Log scale for ratio measures; null line at 1 (ratio) or 0.
function ForestPlot({ rc, reported }: { rc: MetaRecomputed; reported?: { effect?: number; ci_low?: number; ci_high?: number } }) {
  const ratio = rc.ratio;
  const pos = (v: number) => (ratio ? Math.log(Math.max(v, 1e-6)) : v);
  const nullVal = ratio ? 1 : 0;
  const all = [
    ...rc.forest.flatMap((f) => [f.ci_low, f.ci_high]),
    rc.pooled.ci_low, rc.pooled.ci_high, nullVal,
  ].filter((v) => Number.isFinite(v));
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const padL = 150, padR = 56, plotW = 420, rowH = 22;
  const top = 8;
  const rows = rc.forest.length;
  const height = top + rows * rowH + 46;
  const x = (v: number) => {
    const t = (pos(Math.min(Math.max(v, min), max)) - pos(min)) / (pos(max) - pos(min) || 1);
    return padL + t * plotW;
  };
  const fmt = (v: number) => v.toFixed(2);

  return (
    <div className="overflow-x-auto rounded-md border bg-card p-2">
      <svg width={padL + plotW + padR} height={height} className="text-foreground" style={{ minWidth: padL + plotW + padR }}>
        {/* null reference line */}
        <line x1={x(nullVal)} y1={top} x2={x(nullVal)} y2={top + rows * rowH + 6} stroke="currentColor" strokeOpacity={0.25} strokeDasharray="3 3" />
        {/* studies */}
        {rc.forest.map((f, i) => {
          const y = top + i * rowH + rowH / 2;
          const sq = Math.max(3, Math.min(9, Math.sqrt(f.weight) * 1.6));
          return (
            <g key={i}>
              <text x={6} y={y + 3} fontSize={10} fill="currentColor" fillOpacity={0.8}>{trunc(f.label, 26)}</text>
              <line x1={x(f.ci_low)} y1={y} x2={x(f.ci_high)} y2={y} stroke="currentColor" strokeOpacity={0.55} />
              <rect x={x(f.effect) - sq / 2} y={y - sq / 2} width={sq} height={sq} fill="#2563eb" />
              <text x={padL + plotW + 6} y={y + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{f.weight}%</text>
            </g>
          );
        })}
        {/* pooled diamond */}
        {(() => {
          const y = top + rows * rowH + 12;
          const cx = x(rc.pooled.effect), l = x(rc.pooled.ci_low), r = x(rc.pooled.ci_high);
          return (
            <g>
              <polygon points={`${l},${y} ${cx},${y - 6} ${r},${y} ${cx},${y + 6}`} fill="#dc2626" />
              <text x={6} y={y + 3} fontSize={10} fontWeight={600} fill="currentColor">Pooled ({rc.model})</text>
              <text x={padL + plotW + 6} y={y + 3} fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmt(rc.pooled.effect)}</text>
            </g>
          );
        })()}
        {/* reported marker */}
        {typeof reported?.effect === "number" && (
          <g>
            <line x1={x(reported.effect)} y1={top} x2={x(reported.effect)} y2={top + rows * rowH + 18} stroke="#16a34a" strokeOpacity={0.7} strokeWidth={1.5} />
            <text x={x(reported.effect) + 3} y={height - 6} fontSize={9} fill="#16a34a">reported {fmt(reported.effect)}</text>
          </g>
        )}
        {/* axis labels */}
        <text x={padL} y={height - 6} fontSize={9} fill="currentColor" fillOpacity={0.6}>{fmt(min)}</text>
        <text x={padL + plotW} y={height - 6} fontSize={9} fill="currentColor" fillOpacity={0.6} textAnchor="end">{fmt(max)}</text>
      </svg>
    </div>
  );
}

function trunc(str: string, n: number) { return str.length > n ? str.slice(0, n - 1) + "…" : str; }
