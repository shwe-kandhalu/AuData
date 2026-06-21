// AuData — Image Forensics (Detect stage)
// Screens figures for manipulation, duplication, and AI generation.
// Runs copy-move detection, ELA, splicing detection, and cross-paper reuse comparison.

import { useEffect, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import {
  Image, Play, Loader2, X, CheckCircle, AlertCircle, Download, Search,
} from "lucide-react";
import { useStore } from "../lib/store";
import {
  ImageForensicsService, AuditStore, apiConfig, type ImageForensicsSummary, type ImageForensicsReport,
} from "../lib/apiClient";

const SEV_STYLE: Record<string, string> = {
  high: "bg-red-500/10 text-red-600 border-red-500/30",
  moderate: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  low: "bg-sky-500/10 text-sky-600 border-sky-500/30",
};

const SEV_DOT: Record<string, string> = {
  high: "bg-red-500",
  moderate: "bg-amber-500",
  low: "bg-sky-500",
};

export function ImageForensicsPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [running, setRunning] = useState(false);
  const [summary, setSummary] = useState<ImageForensicsSummary | null>(null);
  const [report, setReport] = useState<ImageForensicsReport | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const auditKey = paper?.id || "__none__";
  useEffect(() => {
    let cancelled = false;
    const apply = (a: any) => {
      if (cancelled) return;
      if (a) {
        setSummary(a.summary || null);
        setReport(a.report || null);
        setNote(a.note || null);
      } else {
        setSummary(null);
        setReport(null);
        setNote(null);
      }
    };
    const local = s.imageAudits?.[auditKey];
    if (local) {
      apply(local);
    } else {
      apply(null);
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  function persist(patch: Partial<{ summary: ImageForensicsSummary | null; report: ImageForensicsReport | null; note: string | null }>) {
    const prev = s.imageAudits?.[auditKey] || {};
    const entry = { ...prev, ...patch, ranAt: Date.now() };
    s.setImageAudits?.({ ...(s.imageAudits || {}), [auditKey]: entry });
    if (auditKey !== "__none__") AuditStore.save(auditKey, "images", entry);
  }

  async function run() {
    if (!paper) { setError("Ingest a paper first."); return; }
    if (!paper.has_pdf) { setError("Paper has no PDF — image extraction requires full PDF."); return; }
    
    setError(null);
    setNote(null);
    setSummary(null);
    setReport(null);
    setRunning(true);
    
    const ac = new AbortController();
    abortRef.current = ac;
    
    try {
      const out = await ImageForensicsService.checkPaper(paper.id, { signal: ac.signal });
      setSummary(out.summary);
      setReport(out.report);
      if (out.note) setNote(out.note);
      persist({ summary: out.summary, report: out.report, note: out.note });
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        setError(e?.message || "Image forensics check failed.");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  const findings = report?.cross_paper_findings || [];
  const shown = findings.filter((f) => {
    const searchStr = filter.toLowerCase();
    return (
      f.target_figure.toLowerCase().includes(searchStr) ||
      f.candidate_figure.toLowerCase().includes(searchStr) ||
      f.flag_type.toLowerCase().includes(searchStr)
    );
  });

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Image className="w-6 h-6 text-indigo-600" />
            <div>
              <h2 className="text-xl font-semibold">Image Forensics</h2>
              <p className="text-sm text-muted-foreground">Screen figures for manipulation, duplication, and AI generation</p>
            </div>
          </div>
          <Badge variant={running ? "secondary" : "outline"} className="gap-1">
            {running && <Loader2 className="w-3 h-3 animate-spin" />}
            {running ? "Running..." : "Ready"}
          </Badge>
        </div>

        <div className="flex gap-2 mb-6">
          <Button
            onClick={run}
            disabled={!paper || running}
            className="gap-2"
          >
            <Play className="w-4 h-4" />
            {running ? "Analyzing..." : "Analyze Figures"}
          </Button>
          {running && (
            <Button
              variant="outline"
              onClick={() => abortRef.current?.abort()}
              className="gap-2"
            >
              <X className="w-4 h-4" />
              Cancel
            </Button>
          )}
        </div>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-md text-red-700 text-sm mb-4">
            {error}
          </div>
        )}

        {note && (
          <div className="p-3 bg-blue-50 border border-blue-200 rounded-md text-blue-700 text-sm mb-4">
            {note}
          </div>
        )}

        {summary && (
          <div className="grid grid-cols-4 gap-4 mb-6">
            <div className="p-3 bg-slate-50 rounded-md border border-slate-200">
              <div className="text-xs text-muted-foreground mb-1">Total Figures</div>
              <div className="text-2xl font-bold">{summary.total_images}</div>
            </div>
            <div className="p-3 bg-red-50 rounded-md border border-red-200">
              <div className="text-xs text-red-600 mb-1">Flagged</div>
              <div className="text-2xl font-bold text-red-600">{summary.flagged}</div>
            </div>
            <div className="p-3 bg-amber-50 rounded-md border border-amber-200">
              <div className="text-xs text-amber-600 mb-1">High Severity</div>
              <div className="text-2xl font-bold text-amber-600">{summary.by_severity?.high || 0}</div>
            </div>
            <div className="p-3 bg-emerald-50 rounded-md border border-emerald-200">
              <div className="text-xs text-emerald-600 mb-1">Copy-Move Detected</div>
              <div className="text-2xl font-bold text-emerald-600">{summary.by_flag?.copy_move_detected || 0}</div>
            </div>
          </div>
        )}

        {report?.figure_forensics && report.figure_forensics.length > 0 && (
          <div className="space-y-3 mb-6">
            <h3 className="font-semibold text-sm">Figure-by-Figure Forensics</h3>
            {report.figure_forensics.map((fig, idx) => (
              <div key={idx} className="border rounded-md p-4 space-y-2">
                <div className="text-sm font-medium text-muted-foreground">Figure {idx + 1}</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {fig.copy_move_result && (
                    <div>
                      <div className="text-muted-foreground">Copy-Move Detection</div>
                      <div className="space-y-1">
                        <div>Severity: <span className={`font-medium ${fig.copy_move_result.severity === 'high' ? 'text-red-600' : fig.copy_move_result.severity === 'moderate' ? 'text-amber-600' : 'text-slate-600'}`}>{fig.copy_move_result.severity}</span></div>
                        <div>Matches: {fig.copy_move_result.num_suspicious_matches || 0}</div>
                        {fig.copy_move_result.overlay_path && (
                          <img src={`${apiConfig.baseUrl}/image-forensics/image?filepath=${encodeURIComponent(fig.copy_move_result.overlay_path)}`} alt="Copy-Move overlay" className="max-w-sm border rounded mt-2" />
                        )}
                      </div>
                    </div>
                  )}
                  {fig.splice_result && (
                    <div>
                      <div className="text-muted-foreground">Splice Detection</div>
                      <div className="space-y-1">
                        <div>Severity: <span className={`font-medium ${fig.splice_result.severity === 'high' ? 'text-red-600' : fig.splice_result.severity === 'moderate' ? 'text-amber-600' : 'text-slate-600'}`}>{fig.splice_result.severity}</span></div>
                        <div>Score: {fig.splice_result.score?.toFixed(3)}</div>
                        {fig.splice_result.overlay_path && (
                          <img src={`${apiConfig.baseUrl}/image-forensics/image?filepath=${encodeURIComponent(fig.splice_result.overlay_path)}`} alt="Splice detection overlay" className="max-w-sm border rounded mt-2" />
                        )}
                      </div>
                    </div>
                  )}
                  {fig.ai_generated_score !== undefined && (
                    <div>
                      <div className="text-muted-foreground">AI-Generated Risk</div>
                      <div className={`font-medium ${fig.ai_generated_score >= 0.7 ? 'text-red-600' : fig.ai_generated_score >= 0.5 ? 'text-amber-600' : 'text-emerald-600'}`}>
                        {(fig.ai_generated_score * 100).toFixed(1)}%
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {findings && shown.length > 0 && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 mb-3">
              <Search className="w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Filter findings..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="flex-1"
              />
              <span className="text-sm text-muted-foreground">{shown.length} of {findings.length}</span>
            </div>

            <div className="space-y-2 max-h-96 overflow-y-auto">
              {shown.map((f, i) => (
                <div key={i} className={`p-3 border rounded-md ${SEV_STYLE[f.severity] || "bg-slate-50"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`w-2 h-2 rounded-full ${SEV_DOT[f.severity]}`} />
                        <span className="font-medium text-sm">{f.flag_type}</span>
                        <Badge variant="outline" className="text-xs">{f.severity}</Badge>
                      </div>
                      <div className="text-xs space-y-1">
                        <div><strong>Similarity:</strong> {(f.similarity_score * 100).toFixed(1)}%</div>
                        <div className="text-ellipsis overflow-hidden">
                          <strong>Target:</strong> {f.target_figure.split("/").pop()}
                        </div>
                        <div className="text-ellipsis overflow-hidden">
                          <strong>Candidate:</strong> {f.candidate_figure.split("/").pop()}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {summary && shown.length === 0 && findings.length === 0 && (
          <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-md text-emerald-700 flex items-center gap-2">
            <CheckCircle className="w-5 h-5" />
            <span className="text-sm">No suspicious figures detected.</span>
          </div>
        )}

        {!summary && !running && !error && (
          <div className="p-4 bg-slate-50 border border-slate-200 rounded-md text-slate-600 text-sm text-center">
            Click "Analyze Figures" to screen this paper's figures for manipulation and cross-paper reuse.
          </div>
        )}
      </Card>
    </div>
  );
}
