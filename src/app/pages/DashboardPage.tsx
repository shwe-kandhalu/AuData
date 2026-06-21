// AuData — Dashboard (command center)
// Action-oriented hub for the paper under audit: run / re-run every detector
// from one place, watch progress, and jump to the read-only Audit Report.

import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import {
  LayoutDashboard, Play, Loader2, FileText, Upload, FolderOpen, ArrowRight,
  CheckCircle2, AlertTriangle, Circle, XCircle, Ban,
  Calculator, Sigma, Hash, Image as ImageIcon, GitCompare, BookMarked,
} from "lucide-react";
import { useStore } from "../lib/store";
import {
  AuditStore, ReferenceIntegrityService, MethodsClaimsService, StatisticalAuditService,
  MetaRecreateService, NumericalConsistencyService, ImageForensicsService,
} from "../lib/apiClient";

type RunState = "idle" | "running" | "error";

type Detector = {
  key: string; label: string; icon: any; page: any; needsPdf?: boolean;
  run: (paper: any) => Promise<any>;     // returns the stage data to persist
  storeSetter?: string;                   // store field to update
  flagged: (d: any) => number;
  total: (d: any) => number | undefined;
};

const DETECTORS: Detector[] = [
  {
    key: "statcheck", label: "Statistical Recompute", icon: Calculator, page: "recompute",
    run: (p) => StatisticalAuditService.recompute(p),
    flagged: (d) => d?.mismatch_count ?? 0, total: (d) => d?.claim_count,
  },
  {
    key: "meta", label: "Meta-analysis", icon: Sigma, page: "recompute",
    run: (p) => MetaRecreateService.checkPaper(p.id), storeSetter: "setMetaAudits",
    flagged: (d) => (d?.verdict === "discrepancy" ? 1 : 0), total: (d) => (d?.detected ? 1 : 0),
  },
  {
    key: "numerical", label: "Numerical Consistency", icon: Hash, page: "numerical",
    run: (p) => NumericalConsistencyService.checkPaper(p.id), storeSetter: "setNumericalAudits",
    flagged: (d) => d?.summary?.flagged ?? (d?.flags || []).length, total: (d) => d?.summary?.checked,
  },
  {
    key: "images", label: "Image Forensics", icon: ImageIcon, page: "imaging", needsPdf: true,
    run: async (p) => { const r = await ImageForensicsService.checkPaper(p.id); return { summary: r.summary, report: r.report }; },
    storeSetter: "setImageAudits",
    flagged: (d) => d?.summary?.flagged ?? 0, total: (d) => d?.summary?.total_images,
  },
  {
    key: "methods", label: "Methods ↔ Claims", icon: GitCompare, page: "methods",
    run: async (p) => { const r = await MethodsClaimsService.checkPaper(p.id); return { results: r.results, summary: r.summary, note: r.note }; },
    storeSetter: "setMethodsAudits",
    flagged: (d) => d?.summary?.flagged ?? (d?.results || []).filter((x: any) => x.status === "flagged").length, total: (d) => d?.summary?.total,
  },
  {
    key: "references", label: "Reference Integrity", icon: BookMarked, page: "references",
    run: async (p) => { const r = await ReferenceIntegrityService.checkPaper(p.id, { checkClaims: true }); return { results: r.results, summary: r.summary, metrics: r.metrics }; },
    storeSetter: "setRefAudits",
    flagged: (d) => d?.summary?.flagged ?? (d?.results || []).filter((x: any) => x.status === "flagged").length, total: (d) => d?.summary?.total,
  },
];

export function DashboardPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;
  const [audits, setAudits] = useState<Record<string, any>>({});
  const [runState, setRunState] = useState<Record<string, RunState>>({});
  const [runningAll, setRunningAll] = useState(false);

  const load = useCallback(() => {
    if (!paper) return;
    AuditStore.getAll(paper.id).then((a) => setAudits(a || {}));
  }, [paper]);
  useEffect(() => { load(); }, [load]);

  async function runOne(det: Detector): Promise<void> {
    if (!paper) return;
    if (det.needsPdf && !paper.has_pdf) { setRunState((r) => ({ ...r, [det.key]: "error" })); return; }
    setRunState((r) => ({ ...r, [det.key]: "running" }));
    try {
      const data = await det.run(paper);
      AuditStore.save(paper.id, det.key, data);
      setAudits((prev) => ({ ...prev, [det.key]: data }));
      if (det.storeSetter) {
        const getter = det.storeSetter.slice(3, 4).toLowerCase() + det.storeSetter.slice(4); // setMetaAudits -> metaAudits
        const cur = (s as any)[getter] || {};
        (s as any)[det.storeSetter]({ ...cur, [paper.id]: data });
      }
      setRunState((r) => ({ ...r, [det.key]: "idle" }));
    } catch {
      setRunState((r) => ({ ...r, [det.key]: "error" }));
    }
  }

  async function runAll() {
    if (!paper) return;
    setRunningAll(true);
    for (const det of DETECTORS) {
      if (det.needsPdf && !paper.has_pdf) continue;
      await runOne(det);
    }
    setRunningAll(false);
  }

  if (!paper) {
    return (
      <Card className="space-y-3 p-8 text-center">
        <div className="inline-block rounded-lg bg-primary/10 p-3"><LayoutDashboard className="size-6 text-primary" /></div>
        <h2 className="text-lg font-semibold">No paper under audit yet</h2>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">Ingest a paper (upload a PDF, or pull by DOI / name / URL) to start auditing it, or reopen a previous audit.</p>
        <div className="flex items-center justify-center gap-2 pt-1">
          <Button onClick={() => s.setPage("ingest")}><Upload className="mr-1.5 size-4" />Ingest a paper</Button>
          <Button variant="outline" onClick={() => s.setPage("audits")}><FolderOpen className="mr-1.5 size-4" />Open past audit</Button>
        </div>
      </Card>
    );
  }

  const status = DETECTORS.map((d) => {
    const data = audits[d.key];
    const rs = runState[d.key] || "idle";
    const ran = !!data;
    return { d, data, rs, ran, flagged: ran ? d.flagged(data) : 0, total: ran ? d.total(data) : undefined };
  });
  const ranCount = status.filter((x) => x.ran).length;
  const totalFlags = status.reduce((n, x) => n + (x.ran ? x.flagged : 0), 0);
  const pct = Math.round((ranCount / DETECTORS.length) * 100);

  return (
    <div className="space-y-4">
      {/* paper + actions */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-muted-foreground">Paper under audit</div>
            <h2 className="mt-0.5 text-lg font-semibold leading-snug">{paper.title || paper.id}</h2>
            <p className="text-xs text-muted-foreground">{[paper.authors, paper.year, paper.container].filter(Boolean).join(" · ")}</p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
              {paper.retracted && <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-red-600"><Ban className="size-3" />Retracted</span>}
              {paper.has_pdf && <span className="rounded bg-muted px-1.5 py-0.5">PDF</span>}
              {paper.has_full_text ? `${(paper.char_count || 0).toLocaleString()} chars` : "metadata only"}
              {" · "}{paper.references_detected || 0} refs · {paper.tables_detected || 0} tables · {paper.figures_detected || 0} figures
            </p>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <Button onClick={runAll} disabled={runningAll}>
              {runningAll ? <Loader2 className="mr-1.5 size-4 animate-spin" /> : <Play className="mr-1.5 size-4" />}
              {runningAll ? "Running all…" : "Run all checks"}
            </Button>
            <Button variant="outline" onClick={() => s.setPage("report")}><FileText className="mr-1.5 size-4" />Open report<ArrowRight className="ml-1 size-3.5" /></Button>
          </div>
        </div>

        {/* progress */}
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
            <span>{ranCount} of {DETECTORS.length} detectors run</span>
            <span><span className={`font-semibold ${totalFlags ? "text-amber-600" : "text-emerald-600"}`}>{totalFlags}</span> flag{totalFlags === 1 ? "" : "s"} so far</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      </Card>

      {/* detector control grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {status.map(({ d, rs, ran, flagged, total }) => {
          const Icon = d.icon;
          const blocked = d.needsPdf && !paper.has_pdf;
          const state = rs === "running" ? "running" : rs === "error" ? "error" : !ran ? "idle" : flagged > 0 ? "flag" : "clean";
          const StateIcon = state === "clean" ? CheckCircle2 : state === "flag" ? AlertTriangle : state === "error" ? XCircle : state === "running" ? Loader2 : Circle;
          const color = state === "clean" ? "text-emerald-600" : state === "flag" ? "text-amber-600" : state === "error" ? "text-red-600" : "text-muted-foreground";
          const ring = state === "clean" ? "border-emerald-500/30" : state === "flag" ? "border-amber-500/40" : "border-dashed";
          const statusText = state === "running" ? "Running…" : state === "error" ? (blocked ? "Needs a PDF" : "Failed") : !ran ? "Not run" : flagged > 0 ? `${flagged} flag${flagged === 1 ? "" : "s"}${total ? ` of ${total}` : ""}` : "Clean";
          return (
            <Card key={d.key} className={`p-4 ${ring}`}>
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className="rounded-lg bg-primary/10 p-1.5"><Icon className="size-4 text-primary" /></div>
                  <button onClick={() => s.setPage(d.page)} className="text-sm font-semibold leading-tight hover:underline">{d.label}</button>
                </div>
                <StateIcon className={`size-5 ${color} ${state === "running" ? "animate-spin" : ""}`} />
              </div>
              <div className="mt-3 flex items-center justify-between">
                <span className={`text-sm font-medium ${color}`}>{statusText}</span>
                <Button size="sm" variant="outline" className="h-7 text-xs" disabled={rs === "running" || runningAll || blocked} onClick={() => runOne(d)}>
                  {rs === "running" ? <Loader2 className="mr-1 size-3 animate-spin" /> : <Play className="mr-1 size-3" />}
                  {ran ? "Re-run" : "Run"}
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
