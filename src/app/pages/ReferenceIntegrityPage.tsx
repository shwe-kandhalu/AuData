// AuData — Reference Integrity (Detect stage)
// Audits the ingested article's references: master list on the left, detailed
// checks on the right, paper-level metrics, CSV export. Each reference is
// resolved (Crossref + OpenAlex), retraction-checked, temporally/self-citation/
// usage-checked, and — using the in-text sentence that cites it — claim-checked.

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Input } from "../components/ui/input";
import {
  BookMarked, Play, Loader2, X, Check, AlertTriangle, ExternalLink, Ban, FileQuestion, Download, Search, FileSearch,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { PdfHighlightViewer } from "../components/PdfHighlightViewer";
import { useStore } from "../lib/store";
import {
  ReferenceIntegrityService, SessionStore, apiConfig, type RefInput, type RefResult, type RefSummary, type RefMetrics, type RefSeverity,
} from "../lib/apiClient";

const REF_AUDITS_KEY = "ref_audits";

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
const SEV_ICON: Record<string, string> = { high: "text-red-500", medium: "text-amber-500", low: "text-sky-500", info: "text-slate-400" };
const VERDICT_LABEL: Record<string, string> = {
  supports: "Supports", partial: "Partial", unsupported: "Unsupported", unrelated: "Unrelated",
  unverifiable: "Unverifiable", no_claim: "No claim", skipped: "Not checked", error: "Error",
};
const VERDICT_STYLE: Record<string, string> = {
  supports: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  partial: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  unsupported: "bg-red-500/10 text-red-600 border-red-500/30",
  unrelated: "bg-red-500/10 text-red-600 border-red-500/30",
  unverifiable: "bg-slate-500/10 text-slate-600 border-slate-500/30",
};

const DOI_RE = /10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+/;
function parseInput(text: string): RefInput[] {
  const refs: RefInput[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const [left, ...rest] = t.split("|");
    const head = left.trim();
    const claim = rest.join("|").trim();
    if (DOI_RE.test(head)) refs.push({ doi: (head.match(DOI_RE) || [""])[0], claim });
    else refs.push({ raw: head, claim });
  }
  return refs;
}

type Decision = "accept" | "dismiss";

function csvEscape(v: any): string { return `"${String(v ?? "").replace(/"/g, '""')}"`; }
function buildCsv(results: RefResult[], decisions: Record<number, Decision>): string {
  const cols = ["ref_number", "severity", "status", "input_doi", "input_raw", "in_text_claim", "resolved", "retracted",
    "cited_count", "matched_title", "matched_doi", "year", "authors", "container", "providers",
    "claim_verdict", "claim_confidence", "claim_reasoning", "issues", "issue_details", "url", "reviewer_decision"];
  const rows = results.map((r) => [
    r.number ?? r.index, r.severity, r.status, r.input.doi, r.input.raw, r.input.claim, r.resolved, r.retracted,
    r.cited_count, r.matched.title, r.matched.doi, r.matched.year, r.matched.authors, r.matched.container,
    (r.matched.providers || []).join("; "), r.claim?.verdict, r.claim?.confidence, r.claim?.reasoning,
    r.issues.map((i) => i.code).join("; "), r.issues.map((i) => i.detail || i.label).join(" | "),
    r.matched.url, decisions[r.index] || "",
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

export function ReferenceIntegrityPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<RefResult[]>([]);
  const [summary, setSummary] = useState<RefSummary | null>(null);
  const [metrics, setMetrics] = useState<RefMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [filter, setFilter] = useState("");
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [locateOpen, setLocateOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const manualCount = useMemo(() => parseInput(input).length, [input]);

  // Persistence: each paper's audit is stored keyed by id, so it survives tab
  // switches and refresh (the store autosaves to localStorage + the session).
  const auditKey = paper?.id || "__manual__";
  useEffect(() => {
    const a = s.refAudits[auditKey];
    if (a) {
      setResults(a.results || []); setSummary(a.summary || null); setMetrics(a.metrics || null);
      setDecisions(a.decisions || {});
      setSelected((a.results || []).find((x: RefResult) => x.status === "flagged")?.index ?? (a.results || [])[0]?.index ?? null);
    } else {
      setResults([]); setSummary(null); setMetrics(null); setDecisions({}); setSelected(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  // Restore audits cached in Redis once on mount (localStorage already restored
  // them client-side; this also covers a cleared cache / another tab).
  const redisRestored = useRef(false);
  useEffect(() => {
    if (redisRestored.current) return;
    redisRestored.current = true;
    SessionStore.get(REF_AUDITS_KEY).then((remote) => {
      if (remote && typeof remote === "object") {
        s.setRefAudits({ ...remote, ...s.refAudits }); // local takes precedence, Redis fills gaps
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function persist(patch: Partial<{ results: RefResult[]; summary: RefSummary | null; metrics: RefMetrics | null; decisions: Record<number, Decision> }>) {
    const prev = s.refAudits[auditKey] || {};
    const nextMap = { ...s.refAudits, [auditKey]: { ...prev, ...patch, ranAt: Date.now() } };
    s.setRefAudits(nextMap);                 // store → localStorage + AuData session
    SessionStore.set(REF_AUDITS_KEY, nextMap); // → Redis (short-term, server-side)
  }

  function setDecision(index: number, d: Decision) {
    setDecisions((prev) => {
      const next = { ...prev, [index]: prev[index] === d ? (undefined as any) : d };
      persist({ decisions: next });
      return next;
    });
  }

  async function run() {
    setError(null); setResults([]); setSummary(null); setMetrics(null); setDecisions({}); setSelected(null);
    const ac = new AbortController();
    abortRef.current = ac;
    const onResult = (r: RefResult) => setResults((prev) => {
      const next = [...prev, r].sort((a, b) => a.index - b.index);
      setSelected((cur) => cur ?? (next.find((x) => x.status === "flagged")?.index ?? next[0]?.index ?? null));
      return next;
    });
    setRunning(true);
    try {
      let out;
      if (paper) {
        out = await ReferenceIntegrityService.checkPaper(paper.id, { checkClaims: true, signal: ac.signal, onResult });
      } else {
        const refs = parseInput(input);
        if (!refs.length) { setError("Ingest a paper, or paste references below."); setRunning(false); return; }
        out = await ReferenceIntegrityService.check(refs, { checkClaims: true, signal: ac.signal, onResult });
      }
      setSummary(out.summary); setMetrics(out.metrics);
      persist({ results: out.results, summary: out.summary, metrics: out.metrics, decisions: {} });
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message || "Reference check failed.");
    } finally { setRunning(false); abortRef.current = null; }
  }

  const shown = useMemo(() => {
    let list = flaggedOnly ? results.filter((r) => r.status === "flagged") : results;
    const f = filter.trim().toLowerCase();
    if (f) list = list.filter((r) =>
      (r.matched.title || "").toLowerCase().includes(f) ||
      (r.input.doi || "").toLowerCase().includes(f) ||
      (r.input.raw || "").toLowerCase().includes(f));
    return list;
  }, [results, flaggedOnly, filter]);

  const sel = results.find((r) => r.index === selected) || null;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 shrink-0"><BookMarked className="size-5 text-primary" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <h2 className="text-base font-semibold">Reference Integrity</h2>
                {paper ? (
                  <p className="text-xs text-muted-foreground truncate">
                    Auditing every reference of <span className="font-medium text-foreground">{paper.title || paper.id}</span>
                  </p>
                ) : (
                  <p className="text-xs text-amber-600">No paper ingested — go to Ingest to audit a paper's references, or paste your own below.</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {running ? (
                  <Button variant="outline" size="sm" onClick={() => abortRef.current?.abort()}><X className="size-4 mr-1.5" />Cancel</Button>
                ) : (
                  <Button size="sm" onClick={run} disabled={!paper && !manualCount}><Play className="size-4 mr-1.5" />Run check</Button>
                )}
              </div>
            </div>
            {!paper && (
              <Textarea
                value={input} onChange={(e) => setInput(e.target.value)} disabled={running}
                placeholder={"10.1016/j.cell.2020.01.001 | Drug X reduced tumor size in mice.\nSmith et al. 2019, Nature | Protein Y regulates apoptosis."}
                className="mt-2 min-h-[120px] font-mono text-xs"
              />
            )}
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
          </div>
        </div>
      </Card>

      {/* Summary + metrics + export */}
      {(running || results.length > 0) && (
        <Card className="p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            {running && <span className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Checking… {results.length}</span>}
            <Stat label="Checked" value={summary?.total ?? results.length} />
            <Stat label="Flagged" value={summary?.flagged ?? results.filter((r) => r.status === "flagged").length} tone="amber" />
            <Stat label="Retracted" value={summary?.retracted ?? results.filter((r) => r.retracted).length} tone="red" />
            <Stat label="Unresolved" value={summary?.unresolved ?? results.filter((r) => !r.resolved).length} tone="red" />
            <div className="flex-1" />
            <Button variant="outline" size="sm" disabled={!results.length}
              onClick={() => downloadCsv(`reference-integrity-${(paper?.id || "audit").replace(/[^\w.-]+/g, "_")}.csv`, buildCsv(results, decisions))}>
              <Download className="size-4 mr-1.5" />Export CSV
            </Button>
          </div>
          {metrics && (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground border-t pt-2">
              <Metric label="Self-citation rate" value={`${(metrics.self_citation_rate * 100).toFixed(0)}% (${metrics.self_citations})`} warn={metrics.self_citation_rate >= 0.25} />
              <Metric label="Uncited in text" value={metrics.uncited_count} warn={metrics.uncited_count > 0} />
              <Metric label="Duplicates" value={metrics.duplicate_count} warn={metrics.duplicate_count > 0} />
              <Metric label="Future-dated" value={metrics.future_dated_count} warn={metrics.future_dated_count > 0} />
              <Metric label="Year range" value={metrics.oldest_year && metrics.newest_year ? `${metrics.oldest_year}–${metrics.newest_year}` : "—"} />
              <Metric label="Max times one ref cited" value={metrics.most_cited} />
            </div>
          )}
        </Card>
      )}

      {/* Master–detail */}
      {results.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-[340px_1fr] gap-4">
          <Card className="p-2 space-y-2 self-start">
            <div className="relative px-1">
              <Search className="size-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" className="h-8 pl-8 text-xs" />
            </div>
            <label className="flex items-center gap-2 cursor-pointer text-[11px] text-muted-foreground px-2">
              <Checkbox checked={flaggedOnly} onCheckedChange={(v) => setFlaggedOnly(v === true)} />Flagged only
            </label>
            <div className="max-h-[640px] overflow-y-auto space-y-0.5">
              {shown.map((r) => {
                const active = r.index === selected;
                const label = r.matched.title || r.input.doi || r.input.raw || "(reference)";
                const dec = decisions[r.index];
                return (
                  <button key={r.index} onClick={() => setSelected(r.index)}
                    className={`w-full text-left rounded px-2 py-1.5 flex items-start gap-2 text-xs transition-colors ${active ? "bg-primary/10 border border-primary/30" : "hover:bg-muted border border-transparent"} ${dec === "dismiss" ? "opacity-50" : ""}`}>
                    <span className={`size-2 rounded-full mt-1 shrink-0 ${SEV_DOT[r.severity]}`} title={r.severity} />
                    <span className="flex-1 min-w-0">
                      <span className="block truncate font-medium">{r.number != null ? `[${r.number}] ` : ""}{label}</span>
                      <span className="block truncate text-[10px] text-muted-foreground">
                        {r.retracted ? "retracted · " : ""}{!r.resolved ? "unresolved · " : ""}{r.issues.length ? `${r.issues.length} issue${r.issues.length === 1 ? "" : "s"}` : "ok"}
                      </span>
                    </span>
                    {dec === "accept" && <Check className="size-3 text-primary shrink-0 mt-0.5" />}
                  </button>
                );
              })}
              {shown.length === 0 && <div className="text-xs text-muted-foreground p-3 text-center">No matching references.</div>}
            </div>
          </Card>

          <Card className="p-5 self-start min-h-[300px]">
            {sel ? <Detail r={sel} decision={decisions[sel.index]} onDecide={(d) => setDecision(sel.index, d)}
              canLocate={!!paper?.has_pdf} onLocate={() => setLocateOpen(true)} />
              : <div className="text-sm text-muted-foreground">Select a reference on the left to see its checks.</div>}
          </Card>
        </div>
      )}

      {/* Locate the selected reference inside the PDF (evidence-linked highlight) */}
      <Dialog open={locateOpen} onOpenChange={setLocateOpen}>
        <DialogContent className="max-w-[min(1500px,97vw)] w-[97vw] sm:max-w-[min(1500px,97vw)]">
          <DialogHeader>
            <DialogTitle className="text-sm">
              Locate in PDF{sel?.number != null ? ` — reference [${sel.number}]` : ""}
            </DialogTitle>
          </DialogHeader>
          {paper?.has_pdf && sel && locateOpen && (
            <PdfHighlightViewer
              url={`${apiConfig.baseUrl}/ingest/pdf-file?id=${encodeURIComponent(paper.id)}`}
              terms={termsFor(sel)}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Search terms to highlight a reference inside the PDF: its DOI, the in-text
// marker [N], and the first few title words (whichever the PDF text contains).
function termsFor(r: RefResult): string[] {
  const t: string[] = [];
  if (r.matched.doi) t.push(r.matched.doi);
  if (r.input.doi) t.push(r.input.doi);
  if (r.number != null) t.push(`[${r.number}]`);
  const title = r.matched.title || "";
  if (title) {
    const words = title.split(/\s+/).slice(0, 6).join(" ");
    if (words.length >= 10) t.push(words);
  }
  return Array.from(new Set(t.filter(Boolean)));
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "amber" | "red" }) {
  const c = tone === "red" ? "text-red-600" : tone === "amber" ? "text-amber-600" : "text-foreground";
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-lg font-semibold ${c}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function Metric({ label, value, warn }: { label: string; value: any; warn?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-[10px] uppercase tracking-wide">{label}</span>
      <span className={`font-semibold ${warn ? "text-amber-600" : "text-foreground"}`}>{value}</span>
    </span>
  );
}

function Detail({ r, decision, onDecide, canLocate, onLocate }: {
  r: RefResult; decision?: Decision; onDecide: (d: Decision) => void; canLocate?: boolean; onLocate?: () => void;
}) {
  const claimV = r.claim?.verdict;
  const showClaim = !!claimV && !["skipped", "no_claim"].includes(claimV);
  return (
    <div className="space-y-4">
      {/* Top bar: badges + actions */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className={SEV_STYLE[r.severity] + " capitalize"}>{r.severity === "none" ? "OK" : r.severity}</Badge>
          {r.number != null && <Badge variant="secondary" className="text-[10px]">ref [{r.number}]</Badge>}
          {r.retracted && <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1"><Ban className="size-3" />Retracted</Badge>}
          {!r.resolved && <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1"><FileQuestion className="size-3" />Unresolved</Badge>}
          {typeof r.cited_count === "number" && <span className="text-[11px] text-muted-foreground">cited {r.cited_count}× in text</span>}
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

      {/* Title — full width */}
      <div className="space-y-1">
        {r.resolved ? (
          <a href={r.matched.url || "#"} target="_blank" rel="noreferrer" className="block text-lg font-semibold leading-snug hover:underline">
            {r.matched.title || r.matched.doi}
            <ExternalLink className="inline size-3.5 ml-1.5 text-muted-foreground align-baseline" />
          </a>
        ) : <h3 className="text-lg font-semibold leading-snug text-red-600">Could not resolve this reference</h3>}
        {r.resolved && (r.matched.authors || r.matched.year || r.matched.container) && (
          <p className="text-sm text-muted-foreground">{[r.matched.authors, r.matched.year, r.matched.container].filter(Boolean).join(" · ")}</p>
        )}
      </div>

      {/* Issues with detailed explanations */}
      {r.issues.length > 0 ? (
        <div className="space-y-2.5">
          {r.issues.map((it) => (
            <div key={it.code} className="rounded-md border p-3 space-y-1">
              <div className="flex items-center gap-2">
                <AlertTriangle className={`size-4 ${SEV_ICON[it.severity] || "text-muted-foreground"}`} />
                <span className="text-sm font-medium">{it.label}</span>
                <Badge variant="outline" className={SEV_STYLE[it.severity] + " capitalize text-[10px]"}>{it.severity}</Badge>
              </div>
              {it.detail && <p className="text-xs text-muted-foreground leading-relaxed">{it.detail}</p>}
            </div>
          ))}
        </div>
      ) : <p className="text-sm text-emerald-600">No issues detected for this reference.</p>}

      {/* Claim assessment — only shown when a claim was actually checked */}
      {showClaim && (
        <div className="rounded-md border p-3 space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold">Citation–claim support</span>
            <Badge variant="outline" className={VERDICT_STYLE[claimV] || "bg-muted text-muted-foreground"}>{VERDICT_LABEL[claimV] || claimV}</Badge>
            {typeof r.claim.confidence === "number" && r.claim.confidence > 0 && (
              <span className="text-[11px] text-muted-foreground">confidence {(r.claim.confidence * 100).toFixed(0)}%</span>
            )}
          </div>
          {r.input.claim && <p className="text-xs italic text-muted-foreground">Cited for: “{r.input.claim}”</p>}
          {r.claim.reasoning && <p className="text-sm">{r.claim.reasoning}</p>}
          {r.claim.quote && <p className="text-xs border-l-2 border-primary/40 pl-2 text-muted-foreground">{r.claim.quote}</p>}
        </div>
      )}

      {/* Resolution detail */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <Field label="Cited as" value={r.input.doi || r.input.raw || "—"} mono />
        <Field label="Resolved DOI" value={r.matched.doi || "—"} mono />
        <Field label="Resolved via" value={(r.matched.providers || []).join(" + ") || "—"} />
        {typeof r.title_similarity === "number" && <Field label="Title match" value={`${(r.title_similarity * 100).toFixed(0)}%`} />}
      </div>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: any; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`truncate ${mono ? "font-mono" : ""}`} title={String(value)}>{value}</div>
    </div>
  );
}
