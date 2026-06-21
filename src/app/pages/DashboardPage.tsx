// AuData — Dashboard. Live overview of the paper under audit: metadata + a
// cross-detector summary (what's been run, how many flags), with quick links.

import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import {
  LayoutDashboard, Upload, BookMarked, GitCompare, Calculator, Hash, Image as ImageIcon,
  Ban, FileText, ArrowRight, FolderOpen,
} from "lucide-react";
import { useStore, type PageId } from "../lib/store";

type Built = {
  page: PageId; label: string; icon: any;
  audit: any; // { summary?: { total, flagged, ... } }
};

export function DashboardPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;
  const key = paper?.id || "";

  const built: Built[] = [
    { page: "references", label: "Reference Integrity", icon: BookMarked, audit: s.refAudits[key] },
    { page: "methods", label: "Methods ↔ Claims", icon: GitCompare, audit: s.methodsAudits[key] },
  ];
  const comingSoon: { label: string; icon: any }[] = [
    { label: "Statistical Recompute", icon: Calculator },
    { label: "Numerical Consistency", icon: Hash },
    { label: "Image Forensics", icon: ImageIcon },
  ];

  const totalFlagged = built.reduce((n, b) => n + (b.audit?.summary?.flagged ?? 0), 0);

  if (!paper) {
    return (
      <div className="space-y-4">
        <Card className="p-8 text-center space-y-3">
          <div className="rounded-lg bg-primary/10 p-3 inline-block"><LayoutDashboard className="size-6 text-primary" /></div>
          <h2 className="text-lg font-semibold">No paper under audit yet</h2>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            Ingest a paper (upload a PDF, or pull by DOI / name / URL) to start auditing it, or reopen a previous audit.
          </p>
          <div className="flex items-center justify-center gap-2 pt-1">
            <Button onClick={() => s.setPage("ingest")}><Upload className="size-4 mr-1.5" />Ingest a paper</Button>
            <Button variant="outline" onClick={() => s.setPage("audits")}><FolderOpen className="size-4 mr-1.5" />Open past audit</Button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Paper under audit */}
      <Card className="p-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Paper under audit</span>
              {paper.retracted && <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1"><Ban className="size-3" />Retracted</Badge>}
              {paper.has_pdf && <Badge variant="secondary" className="text-[10px]">PDF</Badge>}
            </div>
            <h2 className="text-lg font-semibold leading-snug">{paper.title || paper.id}</h2>
            <p className="text-xs text-muted-foreground">{[paper.authors, paper.year, paper.container].filter(Boolean).join(" · ")}</p>
            <p className="text-[11px] text-muted-foreground">
              {paper.has_full_text ? `${paper.char_count.toLocaleString()} chars` : "metadata only"} ·
              {" "}{paper.references_detected || 0} refs · {paper.tables_detected || 0} tables · {paper.figures_detected || 0} figures
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <Button variant="outline" size="sm" onClick={() => s.setPage("ingest")}><FileText className="size-4 mr-1.5" />View / change</Button>
            <Button variant="outline" size="sm" onClick={() => s.setPage("audits")}><FolderOpen className="size-4 mr-1.5" />Audits</Button>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Flags so far:</span>
          <span className={`font-semibold ${totalFlagged > 0 ? "text-amber-600" : "text-emerald-600"}`}>{totalFlagged}</span>
          <span className="text-muted-foreground">across {built.filter((b) => b.audit?.summary).length}/{built.length} detectors run</span>
        </div>
      </Card>

      {/* Detectors */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {built.map((b) => {
          const sum = b.audit?.summary;
          const Icon = b.icon;
          return (
            <button key={b.page} onClick={() => s.setPage(b.page)}
              className="text-left rounded-lg border p-4 hover:bg-muted/50 transition-colors group">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2"><Icon className="size-4 text-primary" /><span className="text-sm font-medium">{b.label}</span></div>
                <ArrowRight className="size-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              {sum ? (
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className={`text-2xl font-semibold ${sum.flagged > 0 ? "text-amber-600" : "text-emerald-600"}`}>{sum.flagged}</span>
                  <span className="text-xs text-muted-foreground">flagged of {sum.total}</span>
                </div>
              ) : (
                <div className="mt-2 text-xs text-muted-foreground">Not run yet — click to run</div>
              )}
            </button>
          );
        })}
        {comingSoon.map((c) => {
          const Icon = c.icon;
          return (
            <div key={c.label} className="rounded-lg border border-dashed p-4 opacity-60">
              <div className="flex items-center gap-2"><Icon className="size-4 text-muted-foreground" /><span className="text-sm font-medium">{c.label}</span></div>
              <div className="mt-2 text-xs text-muted-foreground">Coming soon</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
