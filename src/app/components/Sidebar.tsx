import { useEffect, useState } from "react";
import { Card } from "./ui/card";
import { Label } from "./ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { Separator } from "./ui/separator";
import { FileText, X, Microscope, ShieldCheck, Loader2, Users, LayoutDashboard, FileInput, Calculator, Hash, Image as ImageIcon, GitCompare, BookMarked, Gauge } from "lucide-react";
import { useStore, PageId } from "../lib/store";
import { SessionsPanel } from "./SessionsPanel";

const TASK_LABEL: Record<string, string> = {
  "home-analysis": "Strategy analysis",
  "ai-optimize": "AI Optimize",
  "quality-assess": "Quality assessment",
  "abstract-screen": "Abstract screening",
  "fulltext-fetch": "Full-text fetch",
  "full-text-screen": "Full-text screening",
  "snowball": "Citation snowball",
  "snowball-screen": "Snowball screening",
  "table-extract": "Table extraction",
  "text-extract": "Text extraction",
};

// Friendly display names for known model tags. Keep the value field
// pointing at the actual Ollama / provider id; only the label changes.
function formatModelName(m: string): string {
  if (/leads.*mistral/i.test(m)) return "LEADS-Mistral 7B  (default — screening)";
  if (/medgemma.*27b/i.test(m)) return "MedGemma 27B  (clinical)";
  if (/medgemma/i.test(m)) return "MedGemma";
  if (/qwen2\.5.*7b/i.test(m)) return "Qwen 2.5 7B";
  if (/qwen2\.5/i.test(m)) return "Qwen 2.5";
  if (/llama3\.2.*3b/i.test(m)) return "Llama 3.2 3B  (fast)";
  if (/llama3\.1/i.test(m)) return "Llama 3.1";
  if (/llama/i.test(m)) return m.replace(/:latest$/, "");
  return m.replace(/^hf\.co\//, "").replace(/-GGUF.*$/, "").replace(/:latest$/, "");
}

// Audit pipeline, grouped: Manage → Ingest → Detect → Reliability → Report.
const NAV: { id: PageId; label: string; icon: any; group?: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard, group: "Manage" },
  { id: "audits", label: "Audits", icon: Users },
  { id: "ingest", label: "Ingest", icon: FileInput, group: "Ingest" },
  { id: "recompute", label: "Statistical Recompute", icon: Calculator, group: "Detect" },
  { id: "numerical", label: "Numerical Consistency", icon: Hash },
  { id: "imaging", label: "Image Forensics", icon: ImageIcon },
  { id: "methods", label: "Methods ↔ Claims", icon: GitCompare },
  { id: "references", label: "Reference Integrity", icon: BookMarked },
  { id: "reliability", label: "Reliability Layer", icon: Gauge, group: "Reliability" },
  { id: "review", label: "Flag Review", icon: ShieldCheck },
  { id: "report", label: "Audit Report", icon: FileText, group: "Report" },
];

export function Sidebar() {
  const s = useStore();
  const [localModels, setLocalModels] = useState<string[]>([]);
  const [ollamaRunning, setOllamaRunning] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("/api/models/local")
      .then(r => r.json())
      .then(d => {
        const models: string[] = Array.isArray(d.models) ? d.models : [];
        setLocalModels(models);
        setOllamaRunning(!!d.running);
        // Pick a sensible installed model. LEADS-mistral wins by benchmark
        // (recall=1.0, spec=0.68); fall back to medical-tuned > qwen2.5 > llama.
        const leadsTag = models.find(m => /leads.*mistral/i.test(m));
        const isLeadsAlias = s.model === "leads";
        if (isLeadsAlias && leadsTag) {
          // Resolve the "leads" alias to the actual Ollama tag so the dropdown
          // selection matches a real <SelectItem> and renders the friendly name.
          s.setModel(leadsTag);
        } else if (models.length > 0 && !models.includes(s.model) && !/^(claude|gpt|gemini)/.test(s.model)) {
          const preferred = leadsTag
            || models.find(m => /medgemma/i.test(m))
            || models.find(m => /qwen2\.5/i.test(m))
            || models.find(m => /llama3\.1/i.test(m))
            || models[0];
          s.setModel(preferred);
        }
      })
      .catch(() => setOllamaRunning(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <aside className="w-72 shrink-0 border-r bg-muted/30 overflow-y-auto h-screen sticky top-0">
      <div className="p-4">
        <div className="flex items-center gap-2 mb-4">
          <Microscope className="size-5 text-primary" />
          <span className="font-semibold">AuData</span>
        </div>

        {/* Active tasks (persists across page navigation) */}
        {Object.values(s.tasks).filter(t => t.status === "running").length > 0 && (
          <Card className="p-2 mb-3 bg-primary/5 border-primary/30 space-y-1">
            {Object.values(s.tasks)
              .filter(t => t.status === "running")
              .map(t => (
                <div key={t.kind} className="flex items-center gap-2 text-xs">
                  <Loader2 className="size-3 animate-spin text-primary shrink-0" />
                  <div className="flex-1 truncate font-medium">{TASK_LABEL[t.kind] || t.kind}</div>
                  <button
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => s.cancelTask(t.kind)}
                    title="Cancel"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
          </Card>
        )}

        {/* Navigation — pipeline stages with group headers */}
        <nav className="space-y-1 mb-4">
          {NAV.map(n => {
            const Icon = n.icon;
            const active = s.page === n.id;
            return (
              <div key={n.id}>
                {n.group && (
                  <div className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {n.group}
                  </div>
                )}
                <button onClick={() => s.setPage(n.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors ${active ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>
                  <Icon className="size-4" />{n.label}
                </button>
              </div>
            );
          })}
        </nav>

        <Separator className="my-4" />

        <div className="mb-3">
          <SessionsPanel />
        </div>

        <Card className="p-3 mb-3">
          <Label className="mb-2 block">AI Model</Label>
          <Select value={s.model} onValueChange={s.setModel}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {localModels.length > 0 && (
                <>
                  <div className="px-2 py-1 text-xs text-muted-foreground">Local (Ollama)</div>
                  {/* Sort so the LEADS tag floats to the top of the local list. */}
                  {[...localModels]
                    .sort((a, b) => {
                      const aLeads = /leads.*mistral/i.test(a) ? 0 : 1;
                      const bLeads = /leads.*mistral/i.test(b) ? 0 : 1;
                      return aLeads - bLeads || a.localeCompare(b);
                    })
                    .map(m => (
                      <SelectItem key={m} value={m}>{formatModelName(m)}</SelectItem>
                    ))}
                </>
              )}
              <div className="px-2 pt-2 pb-1 text-xs text-muted-foreground">Cloud (API key required)</div>
              <SelectItem value="claude-opus-4-7">Claude Opus 4.7</SelectItem>
              <SelectItem value="claude-sonnet-4-6">Claude Sonnet 4.6</SelectItem>
              <SelectItem value="claude-haiku-4-5">Claude Haiku 4.5</SelectItem>
              <SelectItem value="gpt-4o">GPT-4o</SelectItem>
              <SelectItem value="gpt-4o-mini">GPT-4o mini</SelectItem>
              <SelectItem value="gemini-1.5-pro">Gemini 1.5 Pro</SelectItem>
            </SelectContent>
          </Select>
          {ollamaRunning === false && (
            <p className="text-xs text-amber-600 mt-2">
              Ollama isn't reachable on localhost:11434. Start it with <code className="text-[10px]">ollama serve</code> or pull a model with <code className="text-[10px]">ollama pull &lt;name&gt;</code>.
            </p>
          )}
          {ollamaRunning && localModels.length === 0 && (
            <p className="text-xs text-amber-600 mt-2">
              Ollama is running but no models pulled. Try <code className="text-[10px]">ollama pull qwen2.5</code>.
            </p>
          )}
        </Card>

        {/* Active Databases and Local PDF upload moved to the Ingest page —
            source selection and the paper-under-audit upload belong with
            ingestion, not the global sidebar. */}
      </div>
    </aside>
  );
}
