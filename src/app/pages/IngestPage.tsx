// AuData — Ingest (the entry point of the audit pipeline)
// Load the paper under audit four ways: upload a PDF, pull by DOI, search by
// name, or fetch any URL via Browserbase. Produces one normalized paper object
// (full text + sections + metadata) that the detection agents consume.

import { useEffect, useRef, useState } from "react";
import { Card } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Label } from "../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import {
  Upload, FileText, Hash, Search, Globe, Loader2, ExternalLink, Ban, X, ChevronDown, ChevronRight, FileQuestion,
} from "lucide-react";
import { useStore } from "../lib/store";
import { IngestService, type IngestCandidate, type PaperUnderAudit } from "../lib/apiClient";

export function IngestPage() {
  const s = useStore();
  const paper = s.paperUnderAudit;

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // If the local store has no paper but the server cached one for this session
  // (Redis short-term storage), restore it.
  useEffect(() => {
    if (s.paperUnderAudit) return;
    let cancelled = false;
    IngestService.restoreSession().then((p) => { if (p && !cancelled) s.setPaperUnderAudit(p); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function start(label: string) {
    setError(null);
    setBusy(label);
    const ac = new AbortController();
    abortRef.current = ac;
    return ac;
  }
  function done() { setBusy(null); abortRef.current = null; }

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2.5"><Upload className="size-5 text-primary" /></div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold">Ingest the paper under audit</h2>
            <p className="text-sm text-muted-foreground">
              Upload a PDF, pull by DOI, search by name, or fetch any paper URL via Browserbase. AuData
              extracts the full text, detects sections, tables and figures, and resolves clean metadata —
              ready for the detection agents.
            </p>
          </div>
        </div>
      </Card>

      <Card className="p-5">
        <Tabs defaultValue="upload">
          <TabsList className="mb-4">
            <TabsTrigger value="upload"><Upload className="size-4 mr-1.5" />Upload PDF</TabsTrigger>
            <TabsTrigger value="doi"><Hash className="size-4 mr-1.5" />By DOI</TabsTrigger>
            <TabsTrigger value="search"><Search className="size-4 mr-1.5" />Search by name</TabsTrigger>
            <TabsTrigger value="url"><Globe className="size-4 mr-1.5" />By URL</TabsTrigger>
          </TabsList>

          <TabsContent value="upload">
            <UploadTab busy={busy} onRun={async (file) => {
              const ac = start("upload");
              try { const { paper } = await IngestService.uploadPdf(file, ac.signal); s.setPaperUnderAudit(paper); }
              catch (e: any) { if (e?.name !== "AbortError") setError(e?.message || "Upload failed."); }
              finally { done(); }
            }} />
          </TabsContent>

          <TabsContent value="doi">
            <DoiTab busy={busy} onRun={async (doi, src) => {
              const ac = start("doi");
              try { const r = await IngestService.fetch({ doi, ...src }, ac.signal); s.setPaperUnderAudit(r.paper); if (!r.resolved) setError("DOI did not resolve to a known record — check it."); }
              catch (e: any) { if (e?.name !== "AbortError") setError(e?.message || "Fetch failed."); }
              finally { done(); }
            }} />
          </TabsContent>

          <TabsContent value="search">
            <SearchTab busy={busy} setBusy={setBusy} setError={setError}
              onPick={async (c, src) => {
                const ac = start("doi");
                try { const r = await IngestService.fetch({ doi: c.doi, title: c.title, ...src }, ac.signal); s.setPaperUnderAudit(r.paper); }
                catch (e: any) { if (e?.name !== "AbortError") setError(e?.message || "Fetch failed."); }
                finally { done(); }
              }} />
          </TabsContent>

          <TabsContent value="url">
            <UrlTab busy={busy} onRun={async (url) => {
              const ac = start("url");
              try { const { paper } = await IngestService.fetchUrl(url, ac.signal); s.setPaperUnderAudit(paper); }
              catch (e: any) { if (e?.name !== "AbortError") setError(e?.message || "Browserbase fetch failed."); }
              finally { done(); }
            }} />
          </TabsContent>
        </Tabs>

        {busy && (
          <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            {busy === "url" ? "Fetching via Browserbase (this can take ~10–20s)…"
              : busy === "upload" ? "Parsing PDF…" : "Resolving + fetching…"}
            <button className="text-primary hover:underline ml-2" onClick={() => abortRef.current?.abort()}>cancel</button>
          </div>
        )}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </Card>

      {paper && <PaperPanel paper={paper} onClear={() => s.setPaperUnderAudit(null)} />}
    </div>
  );
}

// ── input tabs ────────────────────────────────────────────────────────────────

function UploadTab({ busy, onRun }: { busy: string | null; onRun: (f: File) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  return (
    <div className="space-y-3">
      <input ref={ref} type="file" accept=".pdf" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) { setName(f.name); onRun(f); } }} />
      <div className="border-2 border-dashed rounded-lg p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f && f.name.toLowerCase().endsWith(".pdf")) { setName(f.name); onRun(f); } }}>
        <FileText className="size-8 mx-auto text-muted-foreground mb-2" />
        <p className="text-sm text-muted-foreground mb-3">Drop a PDF here, or</p>
        <Button onClick={() => ref.current?.click()} disabled={!!busy}><Upload className="size-4 mr-1.5" />Choose PDF</Button>
        {name && <p className="text-xs text-muted-foreground mt-2">{name}</p>}
      </div>
    </div>
  );
}

function DoiTab({ busy, onRun }: { busy: string | null; onRun: (doi: string, src: FetchSrc) => void }) {
  const [doi, setDoi] = useState("");
  const [src, setSrc] = useState<SourceChoice>("auto");
  const run = () => doi.trim() && onRun(doi.trim(), SRC[src]);
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input placeholder="10.1038/s41586-020-2649-2" value={doi} onChange={(e) => setDoi(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} disabled={!!busy} />
        <Button onClick={run} disabled={!!busy || !doi.trim()}>Fetch</Button>
      </div>
      <FullTextSourceSelect value={src} onChange={setSrc} />
    </div>
  );
}

function UrlTab({ busy, onRun }: { busy: string | null; onRun: (url: string) => void }) {
  const [url, setUrl] = useState("");
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input placeholder="https://www.nature.com/articles/… or any paper URL" value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && url.trim() && onRun(url.trim())} disabled={!!busy} />
        <Button onClick={() => onRun(url.trim())} disabled={!!busy || !url.trim()}>Fetch</Button>
      </div>
      <p className="text-xs text-muted-foreground">Loaded in a real cloud browser (Browserbase) — works on JS-rendered and paywalled landing pages, and downloads the linked PDF when available.</p>
    </div>
  );
}

function SearchTab({ busy, setBusy, setError, onPick }: {
  busy: string | null; setBusy: (v: string | null) => void; setError: (v: string | null) => void;
  onPick: (c: IngestCandidate, src: FetchSrc) => void;
}) {
  const [q, setQ] = useState("");
  const [cands, setCands] = useState<IngestCandidate[] | null>(null);
  const [src, setSrc] = useState<SourceChoice>("auto");

  async function search() {
    if (!q.trim()) return;
    setError(null); setBusy("search"); setCands(null);
    try { setCands(await IngestService.search(q.trim(), 6)); }
    catch (e: any) { setError(e?.message || "Search failed."); }
    finally { setBusy(null); }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input placeholder="Paper title or keywords…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()} disabled={!!busy} />
        <Button onClick={search} disabled={!!busy || !q.trim()}><Search className="size-4 mr-1.5" />Search</Button>
      </div>
      <FullTextSourceSelect value={src} onChange={setSrc} />
      {busy === "search" && <p className="text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="size-4 animate-spin" />Searching Crossref…</p>}
      {cands && cands.length === 0 && <p className="text-sm text-muted-foreground">No matches.</p>}
      {cands && cands.length > 0 && (
        <div className="space-y-1.5">
          {cands.map((c, i) => (
            <button key={i} onClick={() => onPick(c, SRC[src])} disabled={!!busy}
              className="w-full text-left p-3 rounded-md border hover:bg-muted transition-colors disabled:opacity-50">
              <div className="text-sm font-medium">{c.title}</div>
              <div className="text-xs text-muted-foreground">
                {[c.authors, c.year, c.container].filter(Boolean).join(" · ")}
              </div>
              <div className="text-[11px] text-muted-foreground font-mono">{c.doi}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Selectable full-text retrieval strategy, mapped to backend flags.
type FetchSrc = { useOpenAccess: boolean; useBrowserbase: boolean };
type SourceChoice = "auto" | "oa" | "browserbase";
const SRC: Record<SourceChoice, FetchSrc> = {
  auto: { useOpenAccess: true, useBrowserbase: true },
  oa: { useOpenAccess: true, useBrowserbase: false },
  browserbase: { useOpenAccess: false, useBrowserbase: true },
};
const SRC_HINT: Record<SourceChoice, string> = {
  auto: "Open-access APIs first, then Browserbase if needed.",
  oa: "Europe PMC · PMC · Unpaywall · arXiv only (clean structured text).",
  browserbase: "Headless cloud browser only (any URL, incl. paywalled landing pages).",
};

function FullTextSourceSelect({ value, onChange }: { value: SourceChoice; onChange: (v: SourceChoice) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <Label className="text-xs text-muted-foreground">Full-text source</Label>
        <Select value={value} onValueChange={(v) => onChange(v as SourceChoice)}>
          <SelectTrigger className="h-8 w-[230px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">Auto (open-access → Browserbase)</SelectItem>
            <SelectItem value="oa">Open-access databases</SelectItem>
            <SelectItem value="browserbase">Browserbase</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <p className="text-[11px] text-muted-foreground">{SRC_HINT[value]}</p>
    </div>
  );
}

// ── paper under audit panel ─────────────────────────────────────────────────

function PaperPanel({ paper, onClear }: { paper: PaperUnderAudit; onClear: () => void }) {
  const [showText, setShowText] = useState(false);
  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Paper under audit</span>
            {paper.retracted && (
              <Badge variant="outline" className="bg-red-500/10 text-red-600 border-red-500/30 gap-1">
                <Ban className="size-3" />Retracted
              </Badge>
            )}
            <Badge variant="outline" className="text-[10px]">{paper.source}</Badge>
          </div>
          <h3 className="text-base font-semibold">{paper.title || "(untitled)"}</h3>
          <p className="text-xs text-muted-foreground">
            {[paper.authors, paper.year, paper.container].filter(Boolean).join(" · ")}
          </p>
          <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap pt-0.5">
            {paper.doi && <a href={paper.url || `https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:underline font-mono">{paper.doi}<ExternalLink className="size-3" /></a>}
            {paper.providers?.length ? <span>via {paper.providers.join(" + ")}</span> : null}
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClear} title="Clear"><X className="size-4" /></Button>
      </div>

      {/* Structure stats */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <Stat label="Pages" value={paper.num_pages ?? "—"} />
        <Stat label="Characters" value={paper.char_count.toLocaleString()} />
        <Stat label="Sections" value={paper.sections.length} />
        <Stat label="Tables" value={paper.tables_detected} />
        <Stat label="Figures" value={paper.figures_detected} />
      </div>

      {/* Full-text status */}
      <div className="text-xs">
        {paper.has_full_text ? (
          <span className="text-emerald-600">Full text extracted — {paper.full_text_source}</span>
        ) : (
          <span className="text-amber-600 inline-flex items-center gap-1"><FileQuestion className="size-3.5" />No full text retrieved (metadata + abstract only). Try the URL tab with Browserbase.</span>
        )}
      </div>

      {/* Abstract */}
      {paper.abstract && (
        <div>
          <div className="text-xs font-semibold mb-1">Abstract</div>
          <p className="text-sm text-muted-foreground">{paper.abstract}</p>
        </div>
      )}

      {/* Sections */}
      {paper.sections.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {paper.sections.map((sec, i) => (
            <Badge key={i} variant="secondary" className="text-[11px]">
              {sec.title} <span className="text-muted-foreground ml-1">{sec.char_count.toLocaleString()}</span>
            </Badge>
          ))}
        </div>
      )}

      {/* Full-text preview */}
      {paper.has_full_text && (
        <div>
          <button onClick={() => setShowText((v) => !v)} className="flex items-center gap-1 text-sm font-medium">
            {showText ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            Full-text preview
          </button>
          {showText && (
            <pre className="mt-2 max-h-80 overflow-auto text-[11px] whitespace-pre-wrap bg-muted/50 rounded p-3 leading-relaxed">
              {paper.full_text.slice(0, 8000)}{paper.full_text.length > 8000 ? "\n\n… (truncated)" : ""}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="rounded-md border p-2 text-center">
      <div className="text-base font-semibold">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
