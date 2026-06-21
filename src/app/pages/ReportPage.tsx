// AuData — Audit Report
// Consolidates every detector's results for the paper under audit into one
// report: an overall severity rollup plus a section per detector (Reference
// Integrity, Methods↔Claims, Statistical Recompute / GRIM / Meta-analysis,
// Numerical Consistency, Image Forensics). Reads the persisted per-paper audit
// stages, so it reflects whatever has been run. Exportable as Markdown.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import {
  FileText, RefreshCw, Download, ArrowRight, Loader2, ShieldCheck,
  BookMarked, GitCompare, Calculator, Hash, Image as ImageIcon, Sigma, Upload,
} from "lucide-react";
import { useStore, type PageId } from "../lib/store";
import { AuditStore, type RefSeverity } from "../lib/apiClient";

type Item = { title: string; severity: RefSeverity; detail: string };
type Norm = { ran: boolean; total: number; flagged: number; items: Item[]; note?: string };

const SECTIONS: { key: string; label: string; page: PageId; icon: any }[] = [
  { key: "statcheck", label: "Statistical Recompute — p-values", page: "recompute", icon: Calculator },
  { key: "meta", label: "Meta-analysis recreation", page: "recompute", icon: Sigma },
  { key: "numerical", label: "Numerical Consistency", page: "numerical", icon: Hash },
  { key: "images", label: "Image Forensics", page: "imaging", icon: ImageIcon },
  { key: "methods", label: "Methods ↔ Claims", page: "methods", icon: GitCompare },
  { key: "references", label: "Reference Integrity", page: "references", icon: BookMarked },
];

const SEV_RANK: Record<string, number> = { high: 4, medium: 3, low: 2, info: 1, none: 0 };
const SEV_STYLE: Record<string, string> = {
  high: "border-red-500/30 bg-red-500/10 text-red-600",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-600",
  low: "border-sky-500/30 bg-sky-500/10 text-sky-600",
  info: "border-slate-500/30 bg-slate-500/10 text-slate-600",
  none: "border-emerald-500/30 bg-emerald-500/10 text-emerald-600",
};
const SEV_DOT: Record<string, string> = {
  high: "bg-red-500", medium: "bg-amber-500", low: "bg-sky-500", info: "bg-slate-400", none: "bg-emerald-500",
};

function sev(x: any): RefSeverity { return (x || "medium") as RefSeverity; }

function normalize(key: string, d: any): Norm | null {
  if (!d) return null;
  if (key === "references") {
    const res = d.results || []; const fl = res.filter((r: any) => r.status === "flagged");
    return { ran: true, total: d.summary?.total ?? res.length, flagged: d.summary?.flagged ?? fl.length,
      items: fl.map((r: any) => ({ title: r.matched?.title || r.input?.raw || `Reference ${r.number ?? ""}`,
        severity: sev(r.severity), detail: (r.issues || []).map((i: any) => i.label).join("; ") })) };
  }
  if (key === "methods") {
    const res = d.results || []; const fl = res.filter((r: any) => r.status === "flagged");
    return { ran: true, total: d.summary?.total ?? res.length, flagged: d.summary?.flagged ?? fl.length,
      items: fl.map((r: any) => ({ title: r.claim, severity: sev(r.severity),
        detail: [r.issue_type, r.reasoning].filter(Boolean).join(" — ") })) };
  }
  if (key === "recompute") {
    const rows = d.rows || []; const fl = rows.filter((r: any) => r.status === "flagged");
    return { ran: true, total: d.summary?.checked ?? rows.length, flagged: d.summary?.flagged ?? fl.length,
      items: fl.map((r: any) => ({ title: r.label, severity: sev(r.severity), detail: r.explanation })) };
  }
  if (key === "statcheck") {
    const f = d.findings || []; const fl = f.filter((x: any) => x.status === "mismatch");
    return { ran: true, total: d.claim_count ?? f.length, flagged: d.mismatch_count ?? fl.length,
      items: fl.map((x: any) => ({ title: x.claim, severity: "high" as RefSeverity,
        detail: x.note || "Reported p-value does not match the recomputed value." })) };
  }
  if (key === "numerical") {
    const flags = (d.flags || []) as any[];
    return { ran: true, total: flags.length, flagged: flags.length,
      items: flags.map((f: any) => ({ title: f.description || f.type || "Inconsistency",
        severity: sev(f.severity), detail: f.excerpt ? `"${f.excerpt}"` : (f.type || "") })) };
  }
  if (key === "images") {
    const sum = d.summary || {};
    const report = d.report || {};
    const mapSev = (x: any): RefSeverity => (x === "moderate" ? "medium" : (x || "medium"));
    const items: Item[] = [];
    for (const f of (report.cross_paper_findings || [])) {
      items.push({ title: `${f.flag_type || "Figure reuse"}: ${f.target_figure || ""} ~ ${f.candidate_figure || ""}`,
        severity: mapSev(f.severity),
        detail: `cross-paper similarity ${typeof f.similarity_score === "number" ? f.similarity_score.toFixed(2) : f.similarity_score}` });
    }
    for (const r of (report.figure_forensics || [])) {
      const fig = r.metadata?.page ? `page ${r.metadata.page}` : "a figure";
      const cm = r.copy_move_result || {}; const sp = r.splice_result || {};
      if (cm.severity && !["low", "none"].includes(cm.severity)) items.push({ title: `Copy-move in ${fig}`, severity: mapSev(cm.severity), detail: "Cloned region detected within the figure." });
      if (sp.severity && !["low", "none"].includes(sp.severity)) items.push({ title: `Splice boundary in ${fig}`, severity: mapSev(sp.severity), detail: "Possible splice / edited boundary." });
      if (typeof r.ai_generated_score === "number" && r.ai_generated_score >= 0.7) items.push({ title: `Possibly AI-generated (${fig})`, severity: "medium", detail: `heuristic score ${r.ai_generated_score.toFixed(2)} (placeholder detector)` });
    }
    return { ran: true, total: sum.total_images ?? report.num_target_figures ?? 0, flagged: sum.flagged ?? items.length, items };
  }
  if (key === "meta") {
    if (!d.detected) return { ran: true, total: 0, flagged: 0, items: [], note: "No meta-analysis detected in this paper." };
    const disc = d.verdict === "discrepancy";
    return { ran: true, total: 1, flagged: disc ? 1 : 0,
      items: disc ? [{ title: `Pooled ${d.measure || ""} discrepancy`, severity: sev(d.severity), detail: d.explanation }] : [],
      note: !disc ? d.explanation : undefined };
  }
  return null;
}

function downloadMd(name: string, md: string) {
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

export function ReportPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;
  const [audits, setAudits] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!paper) return;
    setLoading(true);
    AuditStore.getAll(paper.id).then((a) => setAudits(a || {})).finally(() => setLoading(false));
  }, [paper]);

  useEffect(() => { load(); }, [load]);

  const sections = useMemo(
    () => SECTIONS.map((sec) => ({ ...sec, norm: normalize(sec.key, audits[sec.key]) })),
    [audits],
  );
  const run = sections.filter((x) => x.norm?.ran);
  const totalFlagged = run.reduce((n, x) => n + (x.norm!.flagged || 0), 0);
  const bySev = useMemo(() => {
    const m: Record<string, number> = {};
    for (const x of run) for (const it of x.norm!.items) m[it.severity] = (m[it.severity] || 0) + 1;
    return m;
  }, [run]);

  if (!paper) {
    return (
      <Card className="p-8 text-center space-y-3">
        <div className="inline-block rounded-lg bg-primary/10 p-3"><FileText className="size-6 text-primary" /></div>
        <h2 className="text-lg font-semibold">No paper under audit</h2>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">Ingest a paper and run the detectors, then come back for the consolidated report.</p>
        <Button onClick={() => s.setPage("ingest")}><Upload className="mr-1.5 size-4" />Ingest a paper</Button>
      </Card>
    );
  }

  function buildMarkdown(): string {
    let md = `# AuData audit report\n\n**${paper!.title || paper!.id}**\n\n`;
    md += `${[paper!.authors, paper!.year, paper!.container].filter(Boolean).join(" · ")}\n\n`;
    md += `Generated ${new Date().toLocaleString()}\n\n`;
    md += `**${totalFlagged} flag${totalFlagged === 1 ? "" : "s"}** across ${run.length} detector${run.length === 1 ? "" : "s"} run.\n\n`;
    for (const sec of sections) {
      if (!sec.norm?.ran) continue;
      md += `## ${sec.label}\n\n`;
      if (sec.norm.flagged === 0) { md += `${sec.norm.note || `No issues found (${sec.norm.total} checked).`}\n\n`; continue; }
      for (const it of sec.norm.items) md += `- **[${it.severity}] ${it.title}** — ${it.detail}\n`;
      md += `\n`;
    }
    return md;
  }

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted-foreground">
              Audit report{loading && <Loader2 className="size-3 animate-spin" />}
            </div>
            <h2 className="mt-0.5 text-lg font-semibold leading-snug">{paper.title || paper.id}</h2>
            <p className="text-xs text-muted-foreground">{[paper.authors, paper.year, paper.container].filter(Boolean).join(" · ")}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className={`text-2xl font-semibold ${totalFlagged ? "text-amber-600" : "text-emerald-600"}`}>{totalFlagged}</span>
              <span className="text-sm text-muted-foreground">flag{totalFlagged === 1 ? "" : "s"} across {run.length} detector{run.length === 1 ? "" : "s"} run</span>
              <span className="mx-1 text-muted-foreground">·</span>
              {(["high", "medium", "low", "info"] as const).map((k) => bySev[k] ? (
                <Badge key={k} variant="outline" className={SEV_STYLE[k] + " capitalize"}>{bySev[k]} {k}</Badge>
              ) : null)}
            </div>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <Button variant="outline" size="sm" onClick={load}><RefreshCw className="mr-1.5 size-4" />Refresh</Button>
            <Button size="sm" onClick={() => downloadMd(`audit-report-${(paper.id).replace(/[^\w.-]+/g, "_")}.md`, buildMarkdown())}>
              <Download className="mr-1.5 size-4" />Download report
            </Button>
          </div>
        </div>
      </Card>

      {run.length === 0 && (
        <Card className="p-6 text-center text-sm text-muted-foreground">
          No detectors have been run for this paper yet. Open a detector tab and run it, then refresh.
        </Card>
      )}

      {sections.map((sec) => {
        const Icon = sec.icon;
        const n = sec.norm;
        if (!n?.ran) return null;
        const items = [...n.items].sort((a, b) => (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0));
        return (
          <Card key={sec.key} className="p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Icon className="size-4 text-primary" />
                <span className="text-sm font-semibold">{sec.label}</span>
                <Badge variant="outline" className={n.flagged ? SEV_STYLE.high : SEV_STYLE.none}>
                  {n.flagged} flagged{n.total ? ` / ${n.total}` : ""}
                </Badge>
              </div>
              <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={() => s.setPage(sec.page)}>
                Open<ArrowRight className="ml-1 size-3.5" />
              </Button>
            </div>
            {items.length > 0 ? (
              <ul className="mt-3 space-y-2">
                {items.map((it, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <span className={`mt-1.5 size-2 shrink-0 rounded-full ${SEV_DOT[it.severity]}`} />
                    <span className="min-w-0">
                      <span className="font-medium">{it.title}</span>
                      {it.detail && <span className="text-muted-foreground"> — {it.detail}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 flex items-center gap-1.5 text-sm text-emerald-600">
                <ShieldCheck className="size-4" />{n.note || `No issues found${n.total ? ` (${n.total} checked)` : ""}.`}
              </p>
            )}
          </Card>
        );
      })}

      {run.length > 0 && run.length < SECTIONS.length && (
        <Card className="p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Not yet run:</span>
            {SECTIONS.filter((sec) => !sections.find((x) => x.key === sec.key)?.norm?.ran)
              .map((sec) => (
                <Button key={sec.key} variant="outline" size="sm" className="h-7 text-xs" onClick={() => s.setPage(sec.page)}>
                  <sec.icon className="mr-1 size-3" />{sec.label}
                </Button>
              ))}
          </div>
        </Card>
      )}
    </div>
  );
}
