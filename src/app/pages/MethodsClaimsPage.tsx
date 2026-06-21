// AuData — Methods ↔ Claims (Detect stage)
// Extracts the paper's main claims/conclusions and checks each against its own
// methods + results: over-claiming, causal-from-observational, over-generalization,
// claims not backed by the data, mismatched methods. Master–detail + CSV + PDF locate.

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import {
  Play, Loader2, X, Check, Download, Search, FileSearch, Lightbulb,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { PdfHighlightViewer } from "../components/PdfHighlightViewer";
import { useStore } from "../lib/store";
import {
  MethodsClaimsService, AuditStore, apiConfig, type ClaimResult, type ClaimSummary, type RefSeverity,
} from "../lib/apiClient";

const SEV_STYLE: Record<RefSeverity, string> = {
  high: "bg-red-500/10 text-red-600 border-red-500/30",
  medium: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  low: "bg-sky-500/10 text-sky-600 border-sky-500/30",
  info: "bg-slate-500/10 text-slate-600 border-slate-500/30",
  none: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
};
const SEV_DOT: Record<RefSeverity, string> = {
  high: "bg-red-500", medium: "bg-amber-500", low: "bg-sky-500", info: "bg-slate-400", none: "bg-emerald-500",
};
const VERDICT_LABEL: Record<string, string> = {
  supported: "Supported", overreach: "Over-claim", causal_overreach: "Causal over-reach",
  overgeneralization: "Over-generalized", unsupported: "Unsupported", methods_mismatch: "Methods mismatch",
  skipped: "Not checked", error: "Error",
};
const VERDICT_STYLE: Record<string, string> = {
  supported: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  overreach: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  causal_overreach: "bg-red-500/10 text-red-600 border-red-500/30",
  overgeneralization: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  unsupported: "bg-red-500/10 text-red-600 border-red-500/30",
  methods_mismatch: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  skipped: "bg-muted text-muted-foreground", error: "bg-red-500/10 text-red-600 border-red-500/30",
};

type Decision = "accept" | "dismiss";

function csvEscape(v: any): string { return `"${String(v ?? "").replace(/"/g, '""')}"`; }
function buildCsv(results: ClaimResult[], decisions: Record<number, Decision>): string {
  const cols = ["index", "verdict", "severity", "issue_type", "confidence", "claim", "reasoning", "evidence", "suggestion", "status", "reviewer_decision"];
  const rows = results.map((r) => [
    r.index, r.verdict, r.severity, r.issue_type, r.confidence, r.claim, r.reasoning, r.evidence, r.suggestion, r.status, decisions[r.index] || "",
  ].map(csvEscape).join(","));
  return [cols.join(","), ...rows].join("\n");
}
function downloadCsv(name: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

export function MethodsClaimsPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<ClaimResult[]>([]);
  const [summary, setSummary] = useState<ClaimSummary | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [filter, setFilter] = useState("");
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [locateOpen, setLocateOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const auditKey = paper?.id || "__none__";
  // Reset the view only when the paper under audit changes (and has no saved
  // results yet) — never on a transient store change, so results don't vanish.
  useEffect(() => {
    if (s.methodsAudits[auditKey]) return;
    setResults([]); setSummary(null); setDecisions({}); setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  // Apply saved results from the store (reactive to Dashboard "Run all"); pull
  // from the server once if they are not in the store yet.
  useEffect(() => {
    let cancelled = false;
    const local = s.methodsAudits[auditKey];
    if (local) {
      setResults(local.results || []);
      setSummary(local.summary || null);
      setDecisions(local.decisions || {});
      setSelected((cur) => {
        const list: ClaimResult[] = local.results || [];
        if (cur != null && list.some((x) => x.index === cur)) return cur;
        return list.find((x) => x.status === "flagged")?.index ?? list[0]?.index ?? null;
      });
    } else if (paper) {
      AuditStore.getAll(paper.id).then((audits) => {
        if (cancelled || !audits.methods) return;
        s.setMethodsAudits({ ...s.methodsAudits, [auditKey]: audits.methods });
      });
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey, s.methodsAudits[auditKey]?.results]);

  function persist(patch: Partial<{ results: ClaimResult[]; summary: ClaimSummary | null; decisions: Record<number, Decision> }>) {
    const prev = s.methodsAudits[auditKey] || {};
    const entry = { ...prev, ...patch, ranAt: Date.now() };
    s.setMethodsAudits({ ...s.methodsAudits, [auditKey]: entry });
    if (auditKey !== "__none__") AuditStore.save(auditKey, "methods", entry);
  }
  function setDecision(index: number, d: Decision) {
    setDecisions((prev) => {
      const next = { ...prev, [index]: prev[index] === d ? (undefined as any) : d };
      persist({ decisions: next });
      return next;
    });
  }

  async function run() {
    if (!paper) { setError("Ingest a paper first."); return; }
    setError(null); setNote(null); setResults([]); setSummary(null); setDecisions({}); setSelected(null); setRunning(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const out = await MethodsClaimsService.checkPaper(paper.id, {
        signal: ac.signal,
        onResult: (r) => setResults((prev) => {
          const next = [...prev, r].sort((a, b) => a.index - b.index);
          setSelected((cur) => cur ?? (next.find((x) => x.status === "flagged")?.index ?? next[0]?.index ?? null));
          return next;
        }),
      });
      setSummary(out.summary); if (out.note) setNote(out.note);
      persist({ results: out.results, summary: out.summary, decisions: {} });
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message || "Methods–claims check failed.");
    } finally { setRunning(false); abortRef.current = null; }
  }

  const shown = useMemo(() => {
    let list = flaggedOnly ? results.filter((r) => r.status === "flagged") : results;
    const f = filter.trim().toLowerCase();
    if (f) list = list.filter((r) => r.claim.toLowerCase().includes(f) || (r.issue_type || "").toLowerCase().includes(f));
    return list;
  }, [results, flaggedOnly, filter]);

  const sel = results.find((r) => r.index === selected) || null;

  return (
    <div className="space-y-4">
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {running ? (
            <Button variant="outline" size="sm" onClick={() => abortRef.current?.abort()} className="shrink-0"><X className="size-4 mr-1.5" />Cancel</Button>
          ) : (
            <Button size="sm" onClick={run} disabled={!paper} className="shrink-0"><Play className="size-4 mr-1.5" />{results.length ? "Re-run" : "Run check"}</Button>
          )}
          {running && <span className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Assessing claims… {results.length}</span>}
          {(results.length > 0 || running) && (
            <>
              <Stat label="Claims" value={summary?.total ?? results.length} />
              <Stat label="Flagged" value={summary?.flagged ?? results.filter((r) => r.status === "flagged").length} tone="amber" />
              <Stat label="Supported" value={summary?.supported ?? results.filter((r) => r.verdict === "supported").length} tone="green" />
            </>
          )}
          <div className="flex-1" />
          {results.length > 0 && (
            <Button variant="outline" size="sm" disabled={!results.length}
              onClick={() => downloadCsv(`methods-claims-${(paper?.id || "audit").replace(/[^\w.-]+/g, "_")}.csv`, buildCsv(results, decisions))}>
              <Download className="size-4 mr-1.5" />Export CSV
            </Button>
          )}
        </div>
        {!paper && <p className="text-xs text-amber-600 mt-2">No paper ingested — go to the Ingest tab first.</p>}
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
        {note && <p className="text-sm text-muted-foreground mt-2">{note}</p>}
      </Card>

      {results.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-[360px_1fr] gap-4">
          <Card className="p-2 space-y-2 self-start">
            <div className="relative px-1">
              <Search className="size-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter claims…" className="h-8 pl-8 text-xs" />
            </div>
            <label className="flex items-center gap-2 cursor-pointer text-[11px] text-muted-foreground px-2">
              <Checkbox checked={flaggedOnly} onCheckedChange={(v) => setFlaggedOnly(v === true)} />Flagged only
            </label>
            <div className="max-h-[640px] overflow-y-auto space-y-0.5">
              {shown.map((r) => {
                const active = r.index === selected;
                const dec = decisions[r.index];
                return (
                  <button key={r.index} onClick={() => setSelected(r.index)}
                    className={`w-full text-left rounded px-2 py-1.5 flex items-start gap-2 text-xs transition-colors ${active ? "bg-primary/10 border border-primary/30" : "hover:bg-muted border border-transparent"} ${dec === "dismiss" ? "opacity-50" : ""}`}>
                    <span className={`size-2 rounded-full mt-1 shrink-0 ${SEV_DOT[r.severity]}`} title={r.severity} />
                    <span className="flex-1 min-w-0">
                      <span className="block line-clamp-2">{r.claim}</span>
                      <span className="block truncate text-[10px] text-muted-foreground">{VERDICT_LABEL[r.verdict] || r.verdict}</span>
                    </span>
                    {dec === "accept" && <Check className="size-3 text-primary shrink-0 mt-0.5" />}
                  </button>
                );
              })}
              {shown.length === 0 && <div className="text-xs text-muted-foreground p-3 text-center">No matching claims.</div>}
            </div>
          </Card>

          <Card className="p-5 self-start min-h-[300px]">
            {sel ? <Detail r={sel} decision={decisions[sel.index]} onDecide={(d) => setDecision(sel.index, d)}
              canLocate={!!paper?.has_pdf} onLocate={() => setLocateOpen(true)} />
              : <div className="text-sm text-muted-foreground">Select a claim on the left to see its assessment.</div>}
          </Card>
        </div>
      )}

      <Dialog open={locateOpen} onOpenChange={setLocateOpen}>
        <DialogContent className="max-w-[min(1500px,97vw)] w-[97vw] sm:max-w-[min(1500px,97vw)]">
          <DialogHeader><DialogTitle className="text-sm">Locate claim in PDF</DialogTitle></DialogHeader>
          {paper?.has_pdf && sel && locateOpen && (
            <PdfHighlightViewer
              url={`${apiConfig.baseUrl}/ingest/pdf-file?id=${encodeURIComponent(paper.id)}`}
              terms={[sel.quote, sel.claim.split(/\s+/).slice(0, 8).join(" ")].filter((t): t is string => !!t && t.length >= 4)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "amber" | "green" }) {
  const c = tone === "amber" ? "text-amber-600" : tone === "green" ? "text-emerald-600" : "text-foreground";
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-lg font-semibold ${c}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function Detail({ r, decision, onDecide, canLocate, onLocate }: {
  r: ClaimResult; decision?: Decision; onDecide: (d: Decision) => void; canLocate?: boolean; onLocate?: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className={VERDICT_STYLE[r.verdict] || "bg-muted"}>{VERDICT_LABEL[r.verdict] || r.verdict}</Badge>
          <Badge variant="outline" className={SEV_STYLE[r.severity] + " capitalize text-[10px]"}>{r.severity}</Badge>
          {typeof r.confidence === "number" && r.confidence > 0 && <span className="text-[11px] text-muted-foreground">confidence {(r.confidence * 100).toFixed(0)}%</span>}
        </div>
        <div className="flex gap-1.5 shrink-0">
          {canLocate && <Button variant="outline" size="sm" onClick={onLocate} title="Highlight in the PDF"><FileSearch className="size-3.5 mr-1" />Locate in PDF</Button>}
          <Button variant="outline" size="sm" onClick={() => onDecide("accept")}
            className={decision === "accept" ? "bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-600" : "border-emerald-500/50 text-emerald-700 hover:bg-emerald-500/10 hover:text-emerald-700"}>
            <Check className="size-3.5 mr-1" />Accept</Button>
          <Button variant="outline" size="sm" onClick={() => onDecide("dismiss")}
            className={decision === "dismiss" ? "bg-red-600 hover:bg-red-700 text-white border-red-600" : "border-red-500/50 text-red-600 hover:bg-red-500/10 hover:text-red-600"}>
            <X className="size-3.5 mr-1" />Dismiss</Button>
        </div>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Claim</div>
        <p className="text-base font-medium leading-snug">{r.claim}</p>
        {r.quote && <p className="text-xs italic text-muted-foreground mt-1 border-l-2 border-muted pl-2">“{r.quote}”</p>}
        {r.issue_type && r.verdict !== "supported" && <p className="text-xs text-amber-600 mt-1">{r.issue_type}</p>}
      </div>

      {r.reasoning && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">Assessment</div>
          <p className="text-sm">{r.reasoning}</p>
        </div>
      )}

      {r.evidence && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">From methods / results</div>
          <p className="text-sm border-l-2 border-primary/40 pl-2 text-muted-foreground">{r.evidence}</p>
        </div>
      )}

      {r.suggestion && r.verdict !== "supported" && (
        <div className="rounded-md border border-dashed p-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold mb-1"><Lightbulb className="size-3.5 text-amber-500" />Suggested wording</div>
          <p className="text-sm text-muted-foreground">{r.suggestion}</p>
        </div>
      )}
    </div>
  );
}
