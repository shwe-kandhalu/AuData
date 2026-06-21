// AuData — Image Forensics (Detect stage)
// Screens figures for manipulation and cross-paper reuse, and highlights the
// specific suspicious or matching regions (copy-move, splice, reuse) with the
// actual figure + overlay shown inline. Findings-first, no opaque risk scores.

import { useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Play, Loader2, X, CheckCircle, Copy, Scissors, Sparkles, Files } from "lucide-react";
import { useStore } from "../lib/store";
import {
  ImageForensicsService, AuditStore, apiConfig, type ImageForensicsSummary, type ImageForensicsReport,
} from "../lib/apiClient";

const SEV_STYLE: Record<string, string> = {
  high: "border-red-500/30 bg-red-500/10 text-red-600",
  moderate: "border-amber-500/30 bg-amber-500/10 text-amber-600",
  low: "border-sky-500/30 bg-sky-500/10 text-sky-600",
};
const SEV_DOT: Record<string, string> = { high: "bg-red-500", moderate: "bg-amber-500", low: "bg-sky-500" };
const SEV_RANK: Record<string, number> = { high: 3, moderate: 2, low: 1 };

type Sev = "high" | "moderate" | "low";
type Thumb = { url: string; caption: string };
type Finding = {
  key: string;
  kind: "copy_move" | "splice" | "vlm" | "cross_paper";
  label: string;
  icon: any;
  severity: Sev;
  page?: number;
  description: string;
  thumbs: Thumb[];
};

const imgUrl = (p?: string | null) =>
  p ? `${apiConfig.baseUrl}/forensics/image?path=${encodeURIComponent(p)}` : "";

export function ImageForensicsPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<ImageForensicsSummary | null>(null);
  const [report, setReport] = useState<ImageForensicsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const auditKey = paper?.id || "__none__";
  useEffect(() => {
    let cancelled = false;
    const apply = (a: any) => {
      if (cancelled) return;
      setSummary(a?.summary || null);
      setReport(a?.report || null);
    };
    const local = s.imageAudits?.[auditKey];
    if (local) apply(local);
    else if (paper) {
      apply(null);
      AuditStore.getAll(paper.id).then((audits) => {
        if (cancelled || !audits.images) return;
        s.setImageAudits?.({ ...s.imageAudits, [auditKey]: audits.images });
        apply(audits.images);
      });
    } else apply(null);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey, s.imageAudits?.[auditKey]]);

  function persist(patch: Partial<{ summary: ImageForensicsSummary | null; report: ImageForensicsReport | null }>) {
    const prev = s.imageAudits?.[auditKey] || {};
    const entry = { ...prev, ...patch, ranAt: Date.now() };
    s.setImageAudits?.({ ...(s.imageAudits || {}), [auditKey]: entry });
    if (auditKey !== "__none__") AuditStore.save(auditKey, "images", entry);
  }

  async function run() {
    if (!paper) { setError("Ingest a paper first."); return; }
    if (!paper.has_pdf) { setError("Paper has no PDF — figure extraction requires the full PDF."); return; }
    setError(null); setSummary(null); setReport(null); setRunning(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const out = await ImageForensicsService.checkPaper(paper.id, { signal: ac.signal, useVlm: true });
      setSummary(out.summary); setReport(out.report);
      persist({ summary: out.summary, report: out.report });
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message || "Image forensics check failed.");
    } finally { setRunning(false); abortRef.current = null; }
  }

  // Build a flat, findings-first list — one card per suspicious or matching aspect.
  const findings = useMemo<Finding[]>(() => {
    if (!report) return [];
    const out: Finding[] = [];
    const figs: any[] = report.figure_forensics || [];
    figs.forEach((f, i) => {
      if (f?.status === "error") return;
      const page: number | undefined = f?.metadata?.page;
      const figThumb: Thumb = { url: imgUrl(f.image_path), caption: page ? `Figure · page ${page}` : "Figure" };
      const ela: Thumb | null = f.ela_output_path ? { url: imgUrl(f.ela_output_path), caption: "Error-level analysis" } : null;

      const cm = f.copy_move_result;
      if (cm && (cm.severity === "high" || cm.severity === "moderate")) {
        out.push({
          key: `cm-${i}`, kind: "copy_move", label: "Cloned / copy-move region", icon: Copy,
          severity: cm.severity, page,
          description: "The same content appears in more than one place within this figure — a sign of cloning, duplication, or retouching. The matched regions are highlighted in the overlay.",
          thumbs: [figThumb, cm.overlay_path ? { url: imgUrl(cm.overlay_path), caption: "Matched regions highlighted" } : null, ela].filter(Boolean) as Thumb[],
        });
      }
      const sp = f.splice_result;
      if (sp && (sp.severity === "high" || sp.severity === "moderate")) {
        out.push({
          key: `sp-${i}`, kind: "splice", label: "Possible inserted / spliced region", icon: Scissors,
          severity: sp.severity, page,
          description: "Sharp boundary discontinuities suggest a region may have been inserted or pasted from elsewhere. The suspected boundary is highlighted in the overlay.",
          thumbs: [figThumb, sp.overlay_path ? { url: imgUrl(sp.overlay_path), caption: "Suspected boundary" } : null, ela].filter(Boolean) as Thumb[],
        });
      }
      const v = f.vlm_result;
      if (v && (v.verdict === "manipulation_suspected" || v.verdict === "ai_generated")) {
        out.push({
          key: `vlm-${i}`, kind: "vlm", label: v.verdict === "ai_generated" ? "Possibly AI-generated (vision model)" : "Manipulation suspected (vision model)",
          icon: Sparkles, severity: "moderate", page,
          description: v.reason || "A vision model flagged this figure as potentially manipulated or synthetic. Treat as a lead for manual review, not a verdict.",
          thumbs: [figThumb],
        });
      }
    });

    // Cross-paper reuse (perceptual-hash) — show the two figures side by side.
    (report.cross_paper_findings || []).forEach((cf, i) => {
      const tp = cf.target_metadata?.page, cp = cf.candidate_metadata?.page;
      out.push({
        key: `xp-${i}`, kind: "cross_paper", label: "Cross-paper figure reuse", icon: Files,
        severity: (cf.severity as Sev) || "moderate", page: tp,
        description: "A near-identical figure appears in another paper in your library — possible image reuse across publications. Compare the two side by side.",
        thumbs: [
          { url: imgUrl(cf.target_figure), caption: tp ? `This paper · page ${tp}` : "This paper" },
          { url: imgUrl(cf.candidate_figure), caption: cp ? `Other paper · page ${cp}` : "Other paper" },
        ],
      });
    });

    // Cross-paper reuse (visual embedding match), if vector search ran.
    const vfs: any[] = (report as any).vector_findings || [];
    vfs.forEach((vf, i) => {
      out.push({
        key: `vec-${i}`, kind: "cross_paper", label: "Cross-paper reuse (visual match)", icon: Files,
        severity: (vf.severity as Sev) || "moderate", page: undefined,
        description: "A figure here is visually very similar to one in another paper (semantic embedding match) — a possible reuse the perceptual hash may miss.",
        thumbs: [
          { url: imgUrl(vf.query_panel), caption: "This paper" },
          { url: imgUrl(vf.matched_panel), caption: vf.matched_page ? `Other paper · page ${vf.matched_page}` : "Other paper" },
        ],
      });
    });

    return out.sort((a, b) => (SEV_RANK[b.severity] || 0) - (SEV_RANK[a.severity] || 0));
  }, [report]);

  const analyzed = report?.num_target_figures ?? (report?.figure_forensics?.length || 0);
  const crossPaper = (report?.cross_paper_findings?.length || 0) + ((report as any)?.vector_findings?.length || 0);
  const sevCounts = useMemo(() => {
    const m: Record<string, number> = {};
    findings.forEach((f) => { m[f.severity] = (m[f.severity] || 0) + 1; });
    return m;
  }, [findings]);

  return (
    <div className="space-y-4">
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {running ? (
            <Button size="sm" variant="outline" onClick={() => abortRef.current?.abort()} className="shrink-0"><X className="mr-1.5 size-4" />Cancel</Button>
          ) : (
            <Button size="sm" onClick={run} disabled={!paper} className="shrink-0"><Play className="mr-1.5 size-4" />{summary ? "Re-analyze" : "Analyze figures"}</Button>
          )}
          {summary && (
            <>
              <Stat label="Figures analyzed" value={analyzed} />
              <Stat label="Suspicious findings" value={findings.length} tone={findings.length ? "red" : "green"} />
              <Stat label="Cross-paper matches" value={crossPaper} tone={crossPaper ? "red" : undefined} />
              {(["high", "moderate", "low"] as Sev[]).map((k) => sevCounts[k] ? (
                <Badge key={k} variant="outline" className={SEV_STYLE[k] + " capitalize"}>{sevCounts[k]} {k}</Badge>
              ) : null)}
            </>
          )}
        </div>
        {!paper && <p className="mt-2 text-xs text-amber-600">No paper ingested — go to the Ingest tab first.</p>}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        {running && <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Extracting figures, comparing, and running the vision model… this can take a minute.</p>}
      </Card>

      {summary && (
        <>
          {findings.length > 0 ? (
            <div className="space-y-3">
              {findings.map((f) => {
                const Icon = f.icon;
                return (
                  <Card key={f.key} className="overflow-hidden">
                    <div className={`flex flex-wrap items-center gap-2 border-l-4 p-3 ${f.severity === "high" ? "border-l-red-500" : f.severity === "moderate" ? "border-l-amber-500" : "border-l-sky-500"}`}>
                      <span className={`size-2 rounded-full ${SEV_DOT[f.severity]}`} />
                      <Icon className="size-4 text-muted-foreground" />
                      <span className="text-sm font-medium">{f.label}</span>
                      <Badge variant="outline" className={SEV_STYLE[f.severity] + " capitalize text-[10px]"}>{f.severity}</Badge>
                      {f.page != null && <Badge variant="outline" className="bg-muted text-[10px]">page {f.page}</Badge>}
                    </div>
                    <div className="px-4 pb-4">
                      <p className="text-sm text-muted-foreground">{f.description}</p>
                      <div className="mt-3 flex flex-wrap gap-3">
                        {f.thumbs.map((t, j) => (
                          <a key={j} href={t.url} target="_blank" rel="noreferrer" className="group block">
                            <div className="overflow-hidden rounded-md border bg-muted/40">
                              <img src={t.url} alt={t.caption} loading="lazy"
                                className="max-h-44 w-auto object-contain transition group-hover:opacity-90"
                                onError={(e) => { (e.currentTarget.parentElement?.parentElement as HTMLElement)?.style.setProperty("display", "none"); }} />
                            </div>
                            <div className="mt-1 max-w-[12rem] truncate text-[10px] text-muted-foreground" title={t.caption}>{t.caption}</div>
                          </a>
                        ))}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          ) : (
            <Card className="flex items-center gap-2 p-6 text-sm text-emerald-600">
              <CheckCircle className="size-5" />
              No manipulation or cross-paper reuse detected across {analyzed} figure{analyzed === 1 ? "" : "s"}.
            </Card>
          )}
        </>
      )}

      {!summary && !running && !error && (
        <Card className="p-6 text-center text-sm text-muted-foreground">
          Click <span className="font-medium text-foreground">Analyze figures</span> to extract this paper's figures and screen them for cloning, splicing, and reuse in other papers in your library.
        </Card>
      )}
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
