// AuData — Numerical Consistency (unified)
// One interface for every numerical-consistency check: subgroup N sums,
// percentage vs counts, table vs prose, implausible values, abstract vs results,
// and qualitative quantifiers — plus optional linked-dataset verification.
// Runs server-side (model router), persists per-paper, with triage + CSV + PDF locate.

import { useEffect, useMemo, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Hash, Play, Loader2, X, Check, Download, FileSearch, Database, ChevronDown, ChevronRight } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { PdfHighlightViewer } from "../components/PdfHighlightViewer";
import { useStore } from "../lib/store";
import {
  NumericalConsistencyService, DatasetService, AuditStore, apiConfig,
  type NumericalResult, type NumericalFlag, type RefSeverity,
} from "../lib/apiClient";

const CATEGORIES: { key: string; label: string }[] = [
  { key: "n_sum_error", label: "Subgroup N sums" },
  { key: "percentage_mismatch", label: "Percentage vs counts" },
  { key: "table_text_discrepancy", label: "Table vs prose" },
  { key: "implausible_value", label: "Implausible values" },
  { key: "abstract_results", label: "Abstract vs results" },
  { key: "qualitative_quantifier", label: "Qualitative quantifiers" },
];
const CAT_LABEL: Record<string, string> = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label]));

const SEV_STYLE: Record<string, string> = {
  high: "border-red-500/30 bg-red-500/10 text-red-600",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-600",
  low: "border-sky-500/30 bg-sky-500/10 text-sky-600",
  info: "border-slate-500/30 bg-slate-500/10 text-slate-600",
  none: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600",
};
const SEV_DOT: Record<string, string> = { high: "bg-red-500", medium: "bg-amber-500", low: "bg-sky-500", info: "bg-slate-400", none: "bg-emerald-500" };
const SEV_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

type Decision = "accept" | "dismiss";

function downloadCsv(name: string, flags: NumericalFlag[], decisions: Record<number, Decision>) {
  const esc = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = flags.map((f, i) => [CAT_LABEL[f.type] || f.type, f.severity, f.description, f.excerpt, decisions[i] || ""].map(esc).join(","));
  const csv = ["category,severity,description,excerpt,reviewer_decision", ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

export function NumericalPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;
  const auditKey = paper?.id || "__none__";

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<NumericalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [locate, setLocate] = useState<NumericalFlag | null>(null);
  const [showSummaries, setShowSummaries] = useState(true);

  // dataset verification (secondary)
  const [datasetBusy, setDatasetBusy] = useState(false);
  const [dataset, setDataset] = useState<any>(null);
  const [datasetErr, setDatasetErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apply = (a: any) => {
      if (cancelled) return;
      if (a) { setResult(a.result || a); setDecisions(a.decisions || {}); setDataset(a.dataset || null); }
      else { setResult(null); setDecisions({}); setDataset(null); }
    };
    const local = s.numericalAudits[auditKey];
    if (local) apply(local);
    else if (paper) {
      apply(null);
      AuditStore.getAll(paper.id).then((au) => {
        if (cancelled || !au.numerical) return;
        s.setNumericalAudits({ ...s.numericalAudits, [auditKey]: { result: au.numerical } });
        apply({ result: au.numerical });
      });
    } else apply(null);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  function persist(patch: Record<string, any>) {
    const prev = s.numericalAudits[auditKey] || {};
    const entry = { ...prev, ...patch, ranAt: Date.now() };
    s.setNumericalAudits({ ...s.numericalAudits, [auditKey]: entry });
    if (auditKey !== "__none__") AuditStore.save(auditKey, "numerical", entry.result || entry);
  }
  function setDecision(i: number, d: Decision) {
    setDecisions((prev) => { const next = { ...prev, [i]: prev[i] === d ? (undefined as any) : d }; persist({ decisions: next }); return next; });
  }

  async function run() {
    if (!paper) { setError("Ingest a paper first."); return; }
    setError(null); setResult(null); setDecisions({}); setRunning(true);
    try {
      const out = await NumericalConsistencyService.checkPaper(paper.id);
      setResult(out);
      persist({ result: out, decisions: {} });
    } catch (e: any) { setError(e?.message || "Numerical consistency check failed."); }
    finally { setRunning(false); }
  }

  async function runDataset() {
    if (!paper?.full_text) { setDatasetErr("This paper has no full text for dataset verification."); return; }
    setDatasetErr(null); setDatasetBusy(true);
    try {
      const out = await DatasetService.audit(paper.full_text);
      setDataset(out); persist({ dataset: out });
    } catch (e: any) { setDatasetErr(e?.message || "Dataset verification failed."); }
    finally { setDatasetBusy(false); }
  }

  const flags = result?.flags || [];
  const shown = useMemo(() => {
    const idx = flags.map((f, i) => ({ f, i }));
    const list = flaggedOnly ? idx : idx; // all flags are issues; filter kept for symmetry
    return list.sort((a, b) => (SEV_RANK[b.f.severity] || 0) - (SEV_RANK[a.f.severity] || 0));
  }, [flags, flaggedOnly]);
  const flagsByCat = useMemo(() => {
    const m: Record<string, number> = {};
    for (const f of flags) m[f.type] = (m[f.type] || 0) + 1;
    return m;
  }, [flags]);

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-lg bg-primary/10 p-2"><Hash className="size-5 text-primary" /></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-base font-semibold">Numerical Consistency</h2>
                {paper ? (
                  <p className="truncate text-xs text-muted-foreground">
                    Checking percentages, sums, tables, implausible values, and quantifiers in{" "}
                    <span className="font-medium text-foreground">{paper.title || paper.id}</span>
                  </p>
                ) : <p className="text-xs text-amber-600">No paper ingested — go to the Ingest tab first.</p>}
              </div>
              <Button size="sm" onClick={run} disabled={!paper || running}>
                {running ? <Loader2 className="mr-1.5 size-4 animate-spin" /> : <Play className="mr-1.5 size-4" />}
                {running ? "Checking…" : "Run checks"}
              </Button>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
            {result?.note && <p className="mt-2 text-sm text-muted-foreground">{result.note}</p>}
          </div>
        </div>
      </Card>

      {result && (
        <>
          <Card className="p-3">
            <div className="flex flex-wrap items-center gap-4">
              <Stat label="Categories checked" value={result.summary?.checked ?? CATEGORIES.length} />
              <Stat label="Inconsistencies" value={result.summary?.flagged ?? flags.length} tone={flags.length ? "red" : "green"} />
              {(["high", "medium", "low"] as const).map((k) => result.summary?.by_severity?.[k] ? (
                <Badge key={k} variant="outline" className={SEV_STYLE[k] + " capitalize"}>{result.summary.by_severity[k]} {k}</Badge>
              ) : null)}
              <div className="flex-1" />
              <Button variant="outline" size="sm" disabled={!flags.length}
                onClick={() => downloadCsv(`numerical-${(paper?.id || "audit").replace(/[^\w.-]+/g, "_")}.csv`, flags, decisions)}>
                <Download className="mr-1.5 size-4" />Export CSV
              </Button>
            </div>
          </Card>

          {/* per-category summaries */}
          {result.summaries && Object.keys(result.summaries).length > 0 && (
            <Card className="p-4">
              <button onClick={() => setShowSummaries((v) => !v)} className="flex w-full items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                {showSummaries ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}What each check found
              </button>
              {showSummaries && (
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {CATEGORIES.map((c) => {
                    const n = flagsByCat[c.key] || 0;
                    return (
                      <div key={c.key} className="rounded-md border p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">{c.label}</span>
                          <Badge variant="outline" className={n ? SEV_STYLE.high : SEV_STYLE.none}>{n ? `${n} flagged` : "OK"}</Badge>
                        </div>
                        {result.summaries[c.key] && <p className="mt-1 text-xs text-muted-foreground">{result.summaries[c.key]}</p>}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card>
          )}

          {/* unified flag list */}
          {flags.length > 0 ? (
            <Card className="p-2">
              <label className="flex cursor-pointer items-center gap-2 px-2 py-1 text-[11px] text-muted-foreground">
                <Checkbox checked={flaggedOnly} onCheckedChange={(v) => setFlaggedOnly(v === true)} />Inconsistent only (all rows are flags)
              </label>
              <div className="space-y-2 p-1">
                {shown.map(({ f, i }) => {
                  const dec = decisions[i];
                  return (
                    <div key={i} className={`rounded-md border p-3 ${dec === "dismiss" ? "opacity-50" : ""}`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className={`size-2 rounded-full ${SEV_DOT[f.severity]}`} />
                          <Badge variant="outline" className="bg-muted">{CAT_LABEL[f.type] || f.type}</Badge>
                          <Badge variant="outline" className={SEV_STYLE[f.severity] + " capitalize text-[10px]"}>{f.severity}</Badge>
                        </div>
                        <div className="flex gap-1.5">
                          {paper?.has_pdf && f.excerpt && (
                            <Button variant="outline" size="sm" onClick={() => setLocate(f)}><FileSearch className="mr-1 size-3.5" />Locate</Button>
                          )}
                          <Button variant="outline" size="sm" onClick={() => setDecision(i, "accept")}
                            className={dec === "accept" ? "border-emerald-600 bg-emerald-600 text-white hover:bg-emerald-700" : "border-emerald-500/50 text-emerald-700 hover:bg-emerald-500/10 hover:text-emerald-700"}>
                            <Check className="size-3.5" /></Button>
                          <Button variant="outline" size="sm" onClick={() => setDecision(i, "dismiss")}
                            className={dec === "dismiss" ? "border-red-600 bg-red-600 text-white hover:bg-red-700" : "border-red-500/50 text-red-600 hover:bg-red-500/10 hover:text-red-600"}>
                            <X className="size-3.5" /></Button>
                        </div>
                      </div>
                      <p className="mt-2 text-sm">{f.description}</p>
                      {f.excerpt && <p className="mt-1 border-l-2 border-muted pl-2 text-xs italic text-muted-foreground">“{f.excerpt}”</p>}
                    </div>
                  );
                })}
              </div>
            </Card>
          ) : (
            <Card className="p-6 text-sm text-emerald-600">No numerical inconsistencies found across the six checks.</Card>
          )}
        </>
      )}

      {/* dataset verification (secondary) */}
      {paper && (
        <Card className="space-y-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold"><Database className="size-4 text-primary" />Linked dataset verification</h3>
              <p className="max-w-2xl text-xs text-muted-foreground">Resolve any data-availability links (e.g. Zenodo) and check the paper's numbers against the shared dataset.</p>
            </div>
            <Button size="sm" variant="outline" onClick={runDataset} disabled={datasetBusy || !paper.full_text} className="shrink-0 gap-2">
              {datasetBusy ? <Loader2 className="size-4 animate-spin" /> : <Database className="size-4" />}
              {datasetBusy ? "Checking…" : "Verify datasets"}
            </Button>
          </div>
          {datasetErr && <p className="text-sm text-red-600">{datasetErr}</p>}
          {dataset && (
            <div className="rounded-md border p-3 text-sm">
              {dataset.message && <p className="text-muted-foreground">{dataset.message}</p>}
              {dataset.flag && <Badge variant="outline" className={SEV_STYLE.medium + " mt-1"}>{dataset.flag}</Badge>}
              {Array.isArray(dataset.links) && dataset.links.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs">
                  {dataset.links.map((l: any, i: number) => (
                    <li key={i}><span className="text-muted-foreground">{l.repository}:</span> <a className="text-primary hover:underline" href={l.url} target="_blank" rel="noreferrer">{l.url}</a></li>
                  ))}
                </ul>
              )}
              {!dataset.links?.length && !dataset.message && <p className="text-muted-foreground">No dataset links found in the paper.</p>}
            </div>
          )}
        </Card>
      )}

      <Dialog open={!!locate} onOpenChange={(o) => !o && setLocate(null)}>
        <DialogContent className="w-[97vw] max-w-[min(1500px,97vw)] sm:max-w-[min(1500px,97vw)]">
          <DialogHeader><DialogTitle className="text-sm">Locate in PDF</DialogTitle></DialogHeader>
          {paper?.has_pdf && locate && (
            <PdfHighlightViewer
              url={`${apiConfig.baseUrl}/ingest/pdf-file?id=${encodeURIComponent(paper.id)}`}
              terms={[locate.excerpt].filter((t): t is string => !!t && t.length >= 4)}
            />
          )}
        </DialogContent>
      </Dialog>
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
