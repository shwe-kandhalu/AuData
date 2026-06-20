// AuData — Reference Integrity (Detect stage)
// Resolve each cited reference (Crossref + OpenAlex), check retraction status,
// and assess whether it supports the in-text claim. Pull references straight
// from the paper under audit, or paste your own. Every row is a flag to triage.

import { useMemo, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Badge } from "../components/ui/badge";
import { Checkbox } from "../components/ui/checkbox";
import { Label } from "../components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { BookMarked, Play, Loader2, X, Check, AlertTriangle, ExternalLink, Ban, FileQuestion, FileText } from "lucide-react";
import { useStore } from "../lib/store";
import { ReferenceIntegrityService, type RefInput, type RefResult, type RefSummary, type RefSeverity } from "../lib/apiClient";

const SEV_STYLE: Record<RefSeverity, string> = {
  high: "bg-red-500/10 text-red-600 border-red-500/30",
  medium: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  low: "bg-sky-500/10 text-sky-600 border-sky-500/30",
  info: "bg-slate-500/10 text-slate-600 border-slate-500/30",
  none: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
};
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
  no_claim: "bg-muted text-muted-foreground", skipped: "bg-muted text-muted-foreground",
  error: "bg-red-500/10 text-red-600 border-red-500/30",
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

export function ReferenceIntegrityPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [input, setInput] = useState("");
  const [checkClaims, setCheckClaims] = useState(true);
  const [running, setRunning] = useState(false);
  const [loadingRefs, setLoadingRefs] = useState(false);
  const [results, setResults] = useState<RefResult[]>([]);
  const [summary, setSummary] = useState<RefSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flaggedOnly, setFlaggedOnly] = useState(true);
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const abortRef = useRef<AbortController | null>(null);

  const refCount = useMemo(() => parseInput(input).length, [input]);

  async function loadFromPaper() {
    if (!paper) return;
    setError(null);
    setLoadingRefs(true);
    try {
      const refs = await ReferenceIntegrityService.fromPaper(paper.id);
      if (!refs.length) { setError("No DOIs found in the paper's reference list."); return; }
      setInput(refs.map((r) => r.doi).filter(Boolean).join("\n"));
    } catch (e: any) {
      setError(e?.message || "Could not extract references.");
    } finally { setLoadingRefs(false); }
  }

  async function run() {
    const refs = parseInput(input);
    if (!refs.length) { setError("Add at least one reference (one per line)."); return; }
    setError(null); setResults([]); setSummary(null); setDecisions({}); setRunning(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const { summary } = await ReferenceIntegrityService.check(refs, {
        checkClaims, signal: ac.signal,
        onResult: (r) => setResults((prev) => [...prev, r].sort((a, b) => a.index - b.index)),
      });
      setSummary(summary);
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message || "Reference check failed.");
    } finally { setRunning(false); abortRef.current = null; }
  }

  const shown = flaggedOnly ? results.filter((r) => r.status === "flagged") : results;

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2.5"><BookMarked className="size-5 text-primary" /></div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold">Reference Integrity</h2>
            <p className="text-sm text-muted-foreground">
              Resolve each cited reference against Crossref + OpenAlex, check retraction status, and
              optionally verify it supports the in-text claim. Each row is a flag to accept or dismiss.
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-5 space-y-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <Label>References — one per line (<code className="text-[11px] bg-muted px-1 rounded">DOI or citation | in-text claim</code>)</Label>
          <Button variant="outline" size="sm" onClick={loadFromPaper} disabled={!paper || running || loadingRefs}>
            {loadingRefs ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <FileText className="size-4 mr-1.5" />}
            {paper ? "Load from paper under audit" : "Ingest a paper first"}
          </Button>
        </div>
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={"10.1016/j.cell.2020.01.001 | Drug X reduced tumor size in mice.\nSmith et al. 2019, Nature | Protein Y regulates apoptosis."}
          className="min-h-[150px] font-mono text-xs"
          disabled={running}
        />
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <Checkbox checked={checkClaims} onCheckedChange={(v) => setCheckClaims(v === true)} disabled={running} />
            Check citation–claim support (uses the selected LLM)
          </label>
          <span className="text-xs text-muted-foreground">{refCount} reference{refCount === 1 ? "" : "s"}</span>
          <div className="flex-1" />
          {running ? (
            <Button variant="outline" onClick={() => abortRef.current?.abort()}><X className="size-4 mr-1.5" />Cancel</Button>
          ) : (
            <Button onClick={run} disabled={!refCount}><Play className="size-4 mr-1.5" />Run check</Button>
          )}
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </Card>

      {(running || results.length > 0) && (
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            {running && <span className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Checking… {results.length}/{refCount}</span>}
            <Stat label="Checked" value={summary?.total ?? results.length} />
            <Stat label="Flagged" value={summary?.flagged ?? results.filter((r) => r.status === "flagged").length} tone="amber" />
            <Stat label="Retracted" value={summary?.retracted ?? results.filter((r) => r.retracted).length} tone="red" />
            <Stat label="Unresolved" value={summary?.unresolved ?? results.filter((r) => !r.resolved).length} tone="red" />
            <div className="flex-1" />
            <label className="flex items-center gap-2 cursor-pointer text-xs text-muted-foreground">
              <Checkbox checked={flaggedOnly} onCheckedChange={(v) => setFlaggedOnly(v === true)} />
              Show flagged only
            </label>
          </div>
        </Card>
      )}

      <div className="space-y-2">
        {shown.map((r) => (
          <FlagRow key={r.index} r={r} decision={decisions[r.index]} onDecide={(d) =>
            setDecisions((prev) => ({ ...prev, [r.index]: prev[r.index] === d ? (undefined as any) : d }))
          } />
        ))}
        {!running && results.length > 0 && shown.length === 0 && (
          <Card className="p-6 text-sm text-muted-foreground text-center">
            No flagged references. Untick “Show flagged only” to see all {results.length}.
          </Card>
        )}
      </div>
    </div>
  );
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

function FlagRow({ r, decision, onDecide }: { r: RefResult; decision?: Decision; onDecide: (d: Decision) => void }) {
  const cited = r.input.doi || r.input.raw || "(empty)";
  const claimV = r.claim?.verdict;
  const dimmed = decision === "dismiss";
  return (
    <Card className={`p-4 ${dimmed ? "opacity-50" : ""} ${decision === "accept" ? "border-primary/40" : ""}`}>
      <div className="flex items-start gap-3">
        <Badge variant="outline" className={SEV_STYLE[r.severity] + " mt-0.5 capitalize shrink-0"}>
          {r.severity === "none" ? "OK" : r.severity}
        </Badge>
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            {r.resolved ? (
              <a href={r.matched.url || "#"} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline inline-flex items-center gap-1">
                {r.matched.title || r.matched.doi}<ExternalLink className="size-3 text-muted-foreground" />
              </a>
            ) : (
              <span className="text-sm font-medium text-red-600 inline-flex items-center gap-1">
                <FileQuestion className="size-4" />Unresolved — could not find this reference
              </span>
            )}
            {r.retracted && (
              <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1"><Ban className="size-3" />Retracted</Badge>
            )}
            {r.matched.year ? <span className="text-xs text-muted-foreground">{r.matched.year}</span> : null}
            {r.matched.providers?.length ? <span className="text-[10px] text-muted-foreground">via {r.matched.providers.join(" + ")}</span> : null}
          </div>
          <div className="text-xs text-muted-foreground truncate">Cited as: <span className="font-mono">{cited}</span></div>
          {claimV && claimV !== "skipped" && claimV !== "no_claim" && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-muted-foreground">Claim:</span>
              <Badge variant="outline" className={VERDICT_STYLE[claimV] || "bg-muted"}>{VERDICT_LABEL[claimV] || claimV}</Badge>
              {typeof r.claim.confidence === "number" && r.claim.confidence > 0 && (
                <span className="text-[11px] text-muted-foreground">confidence {(r.claim.confidence * 100).toFixed(0)}%</span>
              )}
              {(r.claim.reasoning || r.claim.quote) && (
                <Popover>
                  <PopoverTrigger asChild><button className="text-[11px] text-primary hover:underline">why?</button></PopoverTrigger>
                  <PopoverContent className="w-80 text-xs space-y-2">
                    {r.input.claim && <p className="italic text-muted-foreground">“{r.input.claim}”</p>}
                    {r.claim.reasoning && <p>{r.claim.reasoning}</p>}
                    {r.claim.quote && <p className="border-l-2 border-primary/40 pl-2 text-muted-foreground">{r.claim.quote}</p>}
                  </PopoverContent>
                </Popover>
              )}
            </div>
          )}
          {r.issues.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {r.issues.map((it) => (
                <span key={it.code} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <AlertTriangle className="size-3 text-amber-500" />{it.label}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col gap-1.5 shrink-0">
          <Button variant={decision === "accept" ? "default" : "outline"} size="sm" className="h-7 px-2" onClick={() => onDecide("accept")} title="Accept this flag"><Check className="size-3.5" /></Button>
          <Button variant={decision === "dismiss" ? "secondary" : "outline"} size="sm" className="h-7 px-2" onClick={() => onDecide("dismiss")} title="Dismiss this flag"><X className="size-3.5" /></Button>
        </div>
      </div>
    </Card>
  );
}
