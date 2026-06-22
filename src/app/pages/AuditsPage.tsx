// AuData — Audits. Every ingested paper, reopenable as the paper under audit,
// with its detection status (flags found per detector).

import { useEffect, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { FolderOpen, Upload, Loader2, RefreshCw, Ban, Check, Search, FileText } from "lucide-react";
import { useStore } from "../lib/store";
import { AuditsService, type AuditListItem } from "../lib/apiClient";

export function AuditsPage() {
  const s = useStore();
  const [items, setItems] = useState<AuditListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  async function refresh() {
    setLoading(true);
    setItems(await AuditsService.list());
    setLoading(false);
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, []);

  async function open(id: string) {
    setOpening(id);
    try {
      const paper = await AuditsService.getPaper(id);
      if (!paper) return;
      s.setPaperUnderAudit(paper);
      s.setStatcheckAudits({});
      s.setNumericalAudits({});
      s.setRefAudits({});
      s.setMethodsAudits({});
      s.setImageAudits({});
      s.setPage("dashboard");
    } finally { setOpening(null); }
  }

  const shown = items.filter((p) =>
    !filter.trim() || (p.title || "").toLowerCase().includes(filter.toLowerCase()) || (p.id || "").toLowerCase().includes(filter.toLowerCase()));

  function flags(id: string) {
    const stat = s.statcheckAudits[id]?.summary?.flagged;
    const num = s.numericalAudits[id]?.summary?.flagged;
    const ref = s.refAudits[id]?.summary?.flagged;
    const mc = s.methodsAudits[id]?.summary?.flagged;
    const img = s.imageAudits[id]?.summary?.flagged;
    const out: string[] = [];
    if (typeof stat === "number") out.push(`${stat} stat`);
    if (typeof num === "number") out.push(`${num} num`);
    if (typeof img === "number") out.push(`${img} image`);
    if (typeof ref === "number") out.push(`${ref} ref`);
    if (typeof mc === "number") out.push(`${mc} claim`);
    return out;
  }

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2"><FolderOpen className="size-5 text-primary" /></div>
            <div>
              <h2 className="text-base font-semibold">Audits</h2>
              <p className="text-xs text-muted-foreground">Every paper you've ingested — open one to make it the paper under audit.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={refresh} disabled={loading}><RefreshCw className={`size-4 mr-1.5 ${loading ? "animate-spin" : ""}`} />Refresh</Button>
            <Button size="sm" onClick={() => s.setPage("ingest")}><Upload className="size-4 mr-1.5" />Ingest new</Button>
          </div>
        </div>
      </Card>

      <Card className="p-3">
        <div className="relative mb-2">
          <Search className="size-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by title or id…" className="h-8 pl-8 text-xs" />
        </div>
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground p-4"><Loader2 className="size-4 animate-spin" />Loading…</div>
        ) : shown.length === 0 ? (
          <div className="text-sm text-muted-foreground p-6 text-center">No audits yet — ingest a paper to get started.</div>
        ) : (
          <div className="space-y-1.5">
            {shown.map((p) => {
              const active = s.paperUnderAudit?.id === p.id;
              const fl = flags(p.id);
              return (
                <div key={p.id}
                  className={`flex items-center gap-3 rounded-md border p-3 ${active ? "bg-primary/5 border-primary/30" : "hover:bg-muted/50"}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium truncate">{p.title || p.id}</span>
                      {active && <Badge variant="secondary" className="text-[10px] gap-1"><Check className="size-3" />current</Badge>}
                      {p.retracted && <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1 text-[10px]"><Ban className="size-3" />retracted</Badge>}
                      {p.has_pdf && <Badge variant="outline" className="text-[10px]">PDF</Badge>}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {[p.authors, p.year, p.source].filter(Boolean).join(" · ")}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {(p.references_detected || 0)} refs · {(p.char_count || 0).toLocaleString()} chars
                      {fl.length > 0 && <span className="text-amber-600"> · flags: {fl.join(", ")}</span>}
                    </div>
                  </div>
                  <Button variant={active ? "secondary" : "outline"} size="sm" onClick={() => open(p.id)} disabled={!!opening}>
                    {opening === p.id ? <Loader2 className="size-4 mr-1.5 animate-spin" /> : <FileText className="size-4 mr-1.5" />}
                    {active ? "Reopen" : "Open"}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
