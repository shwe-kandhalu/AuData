// AuData — Biomedical Research-Integrity Auditor
// ------------------------------------------------------------------
// These are PLACEHOLDER pages, one per feature of the audit pipeline.
// Each carries the spec for the feature it will become: what it does,
// its inputs/outputs, which Evidence-Engine template modules it reuses,
// and what still needs to be built. We fill these in one feature at a
// time. The reusable scaffolding (LLM dispatcher, literature APIs,
// stats engine, session store, SSE streaming, decision/report UI) is
// kept intact in the backend and lib/ and is referenced below.

import { ReactNode, useState, useEffect, useRef } from "react";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  LayoutDashboard, Upload, Calculator, Image as ImageIcon,
  GitCompare, BookMarked, Gauge, ShieldCheck, FileText, Users, Construction,
  AlertTriangle, CheckCircle2, XCircle, Loader2, Sparkles, Play, Hash, Database, Quote,
} from "lucide-react";
import { useStore } from "../lib/store";
import { AuditStore } from "../lib/apiClient";

type Stage = "Ingest" | "Detect" | "Reliability" | "Report" | "Manage";

const STAGE_COLOR: Record<Stage, string> = {
  Ingest: "bg-sky-500/10 text-sky-600 border-sky-500/30",
  Detect: "bg-violet-500/10 text-violet-600 border-violet-500/30",
  Reliability: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  Report: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  Manage: "bg-slate-500/10 text-slate-600 border-slate-500/30",
};

function FeaturePlaceholder(props: {
  icon: any;
  stage: Stage;
  title: string;
  summary: string;
  inputs: string[];
  outputs: string[];
  reuses: ReactNode[];
  toBuild: string[];
}) {
  const { icon: Icon, stage, title, summary, inputs, outputs, reuses, toBuild } = props;
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-lg bg-primary/10 p-3">
            <Icon className="size-6 text-primary" />
          </div>
          <div className="flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold">{title}</h2>
              <Badge variant="outline" className={STAGE_COLOR[stage]}>{stage}</Badge>
              <Badge variant="outline" className="bg-muted text-muted-foreground gap-1">
                <Construction className="size-3" /> Placeholder
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{summary}</p>
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-2">Inputs</h3>
          <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-4">
            {inputs.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </Card>
        <Card className="p-4">
          <h3 className="text-sm font-semibold mb-2">Outputs</h3>
          <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-4">
            {outputs.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </Card>
      </div>

      <Card className="p-4">
        <h3 className="text-sm font-semibold mb-2">Reuses from the Evidence-Engine template</h3>
        <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-4">
          {reuses.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </Card>

      <Card className="p-4 border-dashed">
        <h3 className="text-sm font-semibold mb-2">To build</h3>
        <ul className="space-y-1 text-sm text-muted-foreground list-disc pl-4">
          {toBuild.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </Card>
    </div>
  );
}

const Code = ({ children }: { children: ReactNode }) => (
  <code className="text-[11px] bg-muted px-1 py-0.5 rounded">{children}</code>
);

// ──────────────────────────────────────────────────────────────────
// Manage
// ──────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const pipeline: { stage: Stage; items: string[] }[] = [
    { stage: "Ingest", items: ["Paper under audit + versions"] },
    { stage: "Detect", items: ["Statistical recompute", "Numerical consistency", "Image forensics", "Methods ↔ claims", "Reference integrity"] },
    { stage: "Reliability", items: ["Per-flag calibration", "Conclusion-impact triage", "Flag review (human-in-the-loop)"] },
    { stage: "Report", items: ["Audit report (PDF + JSON)"] },
  ];
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-lg bg-primary/10 p-3"><LayoutDashboard className="size-6 text-primary" /></div>
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">AuData — Research-Integrity Auditor</h2>
            <p className="text-sm text-muted-foreground">
              Audit a single paper or preprint for statistical errors, numerical inconsistencies,
              figure manipulation, methods-vs-claim mismatches, and citation/reference problems —
              surfaced as prioritized, calibrated, evidence-linked flags for human review.
            </p>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-4">
        {pipeline.map((col) => (
          <Card key={col.stage} className="p-4">
            <Badge variant="outline" className={STAGE_COLOR[col.stage] + " mb-3"}>{col.stage}</Badge>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              {col.items.map((it) => <li key={it}>• {it}</li>)}
            </ul>
          </Card>
        ))}
      </div>
      <Card className="p-4 border-dashed text-sm text-muted-foreground">
        Each tab in the sidebar is a placeholder for one feature. Open one to see its spec —
        inputs, outputs, the template modules it reuses, and what's left to build.
      </Card>
    </div>
  );
}

export function AuditsPage() {
  return (
    <FeaturePlaceholder
      icon={Users}
      stage="Manage"
      title="Audits"
      summary="List, open, and manage audit projects. Each audit is one paper-under-audit, its versions, and the flags/decisions/labels collected on it."
      inputs={["A new paper (DOI / URL / PDF) to start an audit", "Existing audits owned by or shared with the user"]}
      outputs={["An audit workspace (the session for the paper under audit)", "Shared review access for human labelers"]}
      reuses={[
        <>Supabase KV store + edge function (<Code>session:</Code>, <Code>project:</Code>, <Code>decision:</Code> namespaces) in <Code>supabase/</Code></>,
        <>Session store snapshot/hydrate in <Code>src/app/lib/store.tsx</Code></>,
        <>Multi-reviewer / invite / role model from the original Projects feature</>,
      ]}
      toBuild={[
        "Reframe the session model from (PICO, papers, decisions, extractions) to (paper-under-audit + versions, flags, decisions, labels)",
        "Extend the KV schema with flags, labels, versions, and reports",
      ]}
    />
  );
}

// ──────────────────────────────────────────────────────────────────
// Ingest
// ──────────────────────────────────────────────────────────────────

export function IngestPage() {
  return (
    <FeaturePlaceholder
      icon={Upload}
      stage="Ingest"
      title="Ingest"
      summary="Load the paper under audit and parse its full structure: sections, statistics, tables, figures, references — with a coordinate map for evidence-linked highlighting. Resolve and diff preprint versions."
      inputs={["A DOI, URL, or uploaded PDF", "Optional: linked data/code repository"]}
      outputs={[
        "Structured document (sections, tables, figures, references)",
        "Coordinate map (page + bbox) for every claim/number/figure → evidence links",
        "Extracted reported statistics, Ns, and claims",
        "Version set (v1/v2/…) for preprints",
      ]}
      reuses={[
        <>Literature fetch + metadata resolution in <Code>Backend/data_services.py</Code> (Crossref / OpenAlex / Europe PMC; arXiv / bioRxiv / medRxiv for versions)</>,
        <>Structured extraction service <Code>AITableExtractor</Code> + <Code>/api/extract/text</Code> → repurposed to pull reported stats, Ns, and claims</>,
        <>LLM dispatcher <Code>AIService.get_model*</Code> in <Code>Backend/utils.py</Code></>,
      ]}
      toBuild={[
        "Full-PDF structure parsing: GROBID + PyMuPDF (template currently only does pypdf, 3 pages / 3k chars)",
        "Table parsing via pdfplumber or Camelot; figure extraction + coordinate map",
        "Version-diff across preprint versions",
      ]}
    />
  );
}

// ──────────────────────────────────────────────────────────────────
// Detect — one placeholder per detection agent
// ──────────────────────────────────────────────────────────────────

export function RecomputePage() {
  return (
    <FeaturePlaceholder
      icon={Calculator}
      stage="Detect"
      title="Statistical Recompute"
      summary="Recompute reported statistics from the paper's own numbers (and, when available, from the linked source data) and flag mismatches. This is the Phase-1 end-to-end vertical slice."
      inputs={["Extracted statistics, Ns, test statistics, p-values, effect sizes", "Optional: linked CSV / dataset"]}
      outputs={["Recompute flags: reported vs recomputed value, delta, severity", "Each flag carries an evidence link to its exact location"]}
      reuses={[
        <>Pure-numpy stats engine in <Code>Backend/meta_analysis.py</Code> (effect sizes, pooling, test statistics)</>,
        <>Structured extraction of reported numbers from Ingest</>,
        <>Decision UI pattern in <Code>src/app/pages/AbstractPage.tsx</Code> → becomes the per-flag triage table</>,
        <>SSE streaming (<Code>/api/simulation/agentic/stream</Code> pattern) to flag live</>,
      ]}
      toBuild={[
        "stats-recompute agent (new AI-service task) wired through the dispatcher",
        "Add scipy / statsmodels for recompute coverage",
        "Sandboxed executor (E2B / Modal) to recompute from linked CSVs, then full code later",
      ]}
    />
  );
}

// ── Types scoped to NumericalPage ──────────────────────────────────
type RecFlag = {
  type: "table_text_discrepancy" | "percentage_mismatch" | "n_sum_error" | "implausible_value" | "other";
  severity: "high" | "medium" | "low";
  description: string;
  excerpt?: string;
};
type QualClaim = {
  id: string;
  qualifier: string;          // e.g. "majority", "most", "few"
  claim: string;              // full sentence
  pct: number | null;         // numeric pct the paper reports (or computed)
  pct_label: string;          // how it appears in paper e.g. "58%" or "78/134"
  implies: ">50" | "<50" | ">80" | "~50" | ">0" | "<20";
  pass: boolean | null;       // null = cannot determine
  finding: string;
};

const SEV_COLOR: Record<string, string> = {
  high: "bg-red-500/10 text-red-600 border-red-500/30",
  medium: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  low: "bg-sky-500/10 text-sky-600 border-sky-500/30",
};
const FLAG_LABEL: Record<string, string> = {
  table_text_discrepancy: "Table↔Text",
  percentage_mismatch: "% Mismatch",
  n_sum_error: "N Sum Error",
  implausible_value: "Implausible Value",
  other: "Other",
};

function mkId() { return Math.random().toString(36).slice(2, 10); }
function extractJson(text: string): string {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start === -1 || end === -1) return text.trim();
  return text.slice(start, end + 1);
}

export function NumericalPage() {
  const store = useStore();
  const { paperUnderAudit: paper, setPage, model } = store;
  const auditKey = paper?.id || "__none__";
  const claudeModel = model.startsWith("claude") ? model : "claude-sonnet-4-6";
  const comparisonRef = useRef<HTMLDivElement>(null);
  // ── paper text (auto-fills from ingested paper) ──────────────────────
  const [paperText, setPaperText] = useState("");
  useEffect(() => {
    if (paper?.has_full_text && paper.full_text && !paperText) setPaperText(paper.full_text);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper?.id]);

  // ── API key (read-only, from env or localStorage) ───────────────────
  const apiKey: string =
    (import.meta as any).env?.VITE_ANTHROPIC_API_KEY ||
    localStorage.getItem("audata:anthropic-key") || "";

  // ── 1. Internal Consistency ──────────────────────────────────────────
  const CONSISTENCY_STEPS: { label: string; desc: string; passMsg: string; type: RecFlag["type"] | null }[] = [
    { label: "Subgroup N sums",         desc: "Do the group sizes add up to the total N?",                          passMsg: "All subgroup Ns sum correctly to their reported totals.",              type: "n_sum_error" },
    { label: "Percentage calculations", desc: "Does count ÷ total × 100 match the reported %?",                    passMsg: "All reported percentages match their underlying counts.",              type: "percentage_mismatch" },
    { label: "Table vs prose",          desc: "Are the same numbers consistent between tables and body text?",      passMsg: "No discrepancies found between table values and body text.",          type: "table_text_discrepancy" },
    { label: "Implausible values",      desc: "Are any means, SDs, or ranges statistically impossible?",           passMsg: "No statistically implausible means, SDs, or ranges detected.",       type: "implausible_value" },
    { label: "Abstract vs results",     desc: "Do numbers in the abstract match what the results section reports?", passMsg: "Numbers in the abstract are consistent with the results section.",  type: "other" },
  ];
  const [consistencyFlags, setConsistencyFlags] = useState<RecFlag[] | null>(null);
  const [consistencySummaries, setConsistencySummaries] = useState<Record<string, string>>({});
  const [consistencyBusy, setConsistencyBusy] = useState(false);
  const [consistencyMsg, setConsistencyMsg] = useState("");
  const [consistencyStep, setConsistencyStep] = useState(0);

  useEffect(() => {
    if (!consistencyBusy) { setConsistencyStep(0); return; }
    const id = setInterval(() => setConsistencyStep(s => (s + 1) % CONSISTENCY_STEPS.length), 2200);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consistencyBusy]);

  async function runConsistency() {
    if (!apiKey) { setConsistencyMsg("Add your Anthropic API key above first."); return; }
    if (!paperText.trim()) { setConsistencyMsg("No paper loaded."); return; }
    setConsistencyBusy(true); setConsistencyFlags(null); setConsistencySummaries({}); setConsistencyMsg("");
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: claudeModel,
          max_tokens: 4096,
          messages: [{ role: "user", content: `You are a biomedical research-integrity auditor. Read this paper carefully and check for internal numerical consistency across five categories. For EVERY category you must write a summary of what you actually found — even if everything checks out.

Paper:
<paper>
${paperText.slice(0, 30000)}
</paper>

Check each category and return ONLY valid JSON in this exact format:
{
  "summaries": {
    "n_sum_error": "What subgroup breakdowns did you find, and do they sum correctly? Name the actual numbers. e.g. 'Found 2 breakdowns: by sex (male=47, female=53, total=100 ✓) and by age group (18-30=32, 31-50=41, 51+=27, total=100 ✓).'",
    "percentage_mismatch": "What percentages did you check? State the count/total and reported % for each. e.g. '3 percentages checked: 42/110=38.2% reported as 38% ✓, 78/134=58.2% reported as 58% ✓, 15/50=30% reported as 30% ✓.'",
    "table_text_discrepancy": "Did the same numbers appear in both tables and prose? State any values you cross-checked. e.g. 'Table 2 reports mean age=34.5; body text states mean age=34.5 ✓. Table 1 N=120 matches Methods section ✓.'",
    "implausible_value": "Are the reported means, SDs, and ranges plausible? Name the values you assessed. e.g. 'Age: M=45.2, SD=12.1 (plausible ✓). Score range 0-100: M=72.3, SD=8.4 (plausible ✓).'",
    "other": "Do abstract numbers match results section numbers? State what you compared. e.g. 'Abstract states N=120 and p<0.05 for primary outcome; Results section confirms N=120 and p=0.03 ✓.'"
  },
  "flags": [
    {"type": "n_sum_error"|"percentage_mismatch"|"table_text_discrepancy"|"implausible_value"|"other", "severity": "high"|"medium"|"low", "description": "exact description naming both conflicting values", "excerpt": "verbatim quote ≤120 chars"}
  ]
}

If a category has no numbers to check, say so in the summary. flags array may be empty.` }],
        }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json() as any;
      const textBlock = data.content?.find((b: any) => b.type === "text");
      const parsed = JSON.parse(extractJson(textBlock?.text ?? "{}"));
      const flags: RecFlag[] = parsed.flags ?? [];
      const summaries: Record<string, string> = parsed.summaries ?? {};
      setConsistencyFlags(flags);
      setConsistencySummaries(summaries);
      const message = flags.length === 0 ? "No internal inconsistencies found." : `${flags.length} issue${flags.length !== 1 ? "s" : ""} found.`;
      setConsistencyMsg(message);
      persistNumerical({ consistencyFlags: flags, consistencySummaries: summaries, consistencyMsg: message });
    } catch (e: any) {
      setConsistencyMsg(`Error: ${e.message}`);
    } finally {
      setConsistencyBusy(false);
    }
  }

  // ── 2. Qualitative claims ────────────────────────────────────────────

  // ── Qualitative quantifier consistency ──────────────────────────────
  const [qualClaims, setQualClaims] = useState<QualClaim[]>([]);
  const [extractingQual, setExtractingQual] = useState(false);
  const [qualMsg, setQualMsg] = useState("");

  function impliesThreshold(q: QualClaim["implies"], pct: number): boolean {
    switch (q) {
      case ">50":  return pct > 50;
      case "<50":  return pct < 50;
      case ">80":  return pct > 80;
      case "~50":  return pct >= 40 && pct <= 60;
      case ">0":   return pct > 0;
      case "<20":  return pct < 20;
    }
  }

  async function extractQualClaims() {
    if (!apiKey) { setQualMsg("Add your Anthropic API key above first."); return; }
    if (!paperText.trim()) { setQualMsg("No paper text loaded."); return; }
    setExtractingQual(true); setQualMsg(""); setQualClaims([]);

    const prompt = `You are a biomedical research-integrity auditor. Find every sentence in the paper that uses a qualitative quantifier ("majority", "most", "minority", "few", "nearly all", "vast majority", "predominantly", "largely", "primarily", "about half", "more than half", "less than half", "small proportion", "large proportion") AND can be checked against a percentage or count in the same paper.

For each such claim:
- qualifier: the specific word/phrase used (e.g. "majority")
- claim: the full sentence (verbatim or near-verbatim)
- pct: the numeric percentage that supports or contradicts the claim (as a number 0-100), or null if no specific number is given
- pct_label: how the number appears in the paper (e.g. "58%", "78 of 134", "N=78 out of 134")
- implies: one of ">50", "<50", ">80", "~50", ">0", "<20" — what the qualifier logically requires

Rules:
- "majority" / "most" / "predominantly" / "largely" / "primarily" / "more than half" → implies ">50"
- "nearly all" / "vast majority" / "almost all" → implies ">80"
- "minority" / "few" / "small proportion" / "less than half" → implies "<50"
- "about half" / "approximately half" → implies "~50"
- "a few" / "very few" / "rarely" → implies "<20"
- Only include claims where you can find or infer a percentage from the paper text

Return ONLY valid JSON:
{"claims": [{"qualifier": "...", "claim": "...", "pct": 58.2, "pct_label": "58.2%", "implies": ">50"}]}

Paper:
<paper>
${paperText.slice(0, 20000)}
</paper>`;

    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: claudeModel,
          max_tokens: 2048,
          messages: [{ role: "user", content: prompt }],
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as any;
        throw new Error(err?.error?.message ?? `API error ${res.status}`);
      }
      const data = await res.json() as any;
      const textBlock = data.content?.find((b: any) => b.type === "text");
      const raw = extractJson(textBlock?.text ?? "{}");
      const parsed = JSON.parse(raw);
      const claims: QualClaim[] = (parsed.claims ?? []).map((c: any) => {
        const pct: number | null = c.pct != null ? Number(c.pct) : null;
        const pass = pct != null ? impliesThreshold(c.implies, pct) : null;
        const finding = pct == null
          ? "No supporting number found in the excerpt."
          : pass
            ? `${c.pct_label} is consistent with "${c.qualifier}".`
            : `${c.pct_label} does not support "${c.qualifier}" (requires ${c.implies === ">50" ? ">50%" : c.implies === "<50" ? "<50%" : c.implies === ">80" ? ">80%" : c.implies === "~50" ? "~50%" : c.implies === "<20" ? "<20%" : ">0%"}).`;
        return { id: mkId(), qualifier: c.qualifier, claim: c.claim, pct, pct_label: c.pct_label ?? "", implies: c.implies, pass, finding };
      });
      setQualClaims(claims);
      const failures     = claims.filter(c => c.pass === false).length;
      const consistent   = claims.filter(c => c.pass === true).length;
      const unverifiable = claims.filter(c => c.pass === null).length;
      const parts = [
        consistent   > 0 ? `${consistent} consistent`              : "",
        failures     > 0 ? `⚠ ${failures} inconsistent`           : "",
        unverifiable > 0 ? `${unverifiable} couldn't be verified` : "",
      ].filter(Boolean).join(", ");
      const message = claims.length === 0
        ? "No checkable qualitative claims found."
        : `Found ${claims.length} claim${claims.length !== 1 ? "s" : ""}: ${parts}.`;
      setQualMsg(message);
      persistNumerical({ qualClaims: claims, qualMsg: message });
    } catch (e: any) {
      setQualMsg(`Error: ${e.message}`);
    } finally {
      setExtractingQual(false);
    }
  }

  // ── Dataset verification ─────────────────────────────────────────────
  type DatasetFile = { url: string; rows: number; columns: string[]; stats: Record<string, any> };
  type DatasetResult = {
    has_dataset: boolean;
    has_availability_statement: boolean;
    flag: string | null;
    message: string | null;
    links: { url: string; repository: string; type: string; accession?: string }[];
    datasets: {
      link: { url: string; repository: string };
      page_ok: boolean;
      final_url: string;
      page_summary: string;
      download_urls: string[];
      files: DatasetFile[];
    }[];
  };
  type ComparisonResult = {
    matches: { item: string; paper: string; dataset: string }[];
    discrepancies: { item: string; paper: string; dataset: string; note: string }[];
    unverifiable: { item: string; reason: string }[];
    summary: string;
  };
  const [datasetResult, setDatasetResult] = useState<DatasetResult | null>(null);
  const [datasetBusy, setDatasetBusy] = useState(false);
  const [datasetMsg, setDatasetMsg] = useState("");
  const [datasetComparison, setDatasetComparison] = useState<{ file: DatasetFile; result: ComparisonResult } | null>(null);
  const [comparingDataset, setComparingDataset] = useState(false);

  type NumericalAuditPatch = Partial<{
    consistencyFlags: RecFlag[] | null;
    consistencySummaries: Record<string, string>;
    consistencyMsg: string;
    qualClaims: QualClaim[];
    qualMsg: string;
    datasetResult: DatasetResult | null;
    datasetMsg: string;
    datasetComparison: { file: DatasetFile; result: ComparisonResult } | null;
  }>;

  function numericalSummary(patch: NumericalAuditPatch = {}) {
    const nextConsistencyFlags = patch.consistencyFlags !== undefined ? patch.consistencyFlags : consistencyFlags;
    const nextQualClaims = patch.qualClaims !== undefined ? patch.qualClaims : qualClaims;
    const nextDatasetResult = patch.datasetResult !== undefined ? patch.datasetResult : datasetResult;
    const nextDatasetComparison = patch.datasetComparison !== undefined ? patch.datasetComparison : datasetComparison;
    let total = 0;
    let flagged = 0;

    if (nextConsistencyFlags !== null) {
      total += CONSISTENCY_STEPS.length;
      flagged += nextConsistencyFlags.length;
    }
    if (nextQualClaims.length > 0 || patch.qualMsg || qualMsg) {
      total += Math.max(nextQualClaims.length, 1);
      flagged += nextQualClaims.filter((claim) => claim.pass === false).length;
    }
    if (nextDatasetResult) {
      total += 1;
      if (nextDatasetResult.flag) flagged += 1;
    }
    if (nextDatasetComparison) {
      total += Math.max(nextDatasetComparison.result.matches.length + nextDatasetComparison.result.discrepancies.length + nextDatasetComparison.result.unverifiable.length, 1);
      flagged += nextDatasetComparison.result.discrepancies.length;
    }

    return { total, flagged };
  }

  function persistNumerical(patch: NumericalAuditPatch) {
    if (!paper || auditKey === "__none__") return;
    const prev = store.numericalAudits[auditKey] || {};
    const entry = {
      ...prev,
      ...patch,
      summary: numericalSummary(patch),
      ranAt: Date.now(),
    };
    store.setNumericalAudits({ ...store.numericalAudits, [auditKey]: entry });
    AuditStore.save(auditKey, "numerical", entry);
  }

  useEffect(() => {
    const saved = store.numericalAudits[auditKey];
    if (!saved) return;
    setConsistencyFlags(saved.consistencyFlags ?? null);
    setConsistencySummaries(saved.consistencySummaries ?? {});
    setConsistencyMsg(saved.consistencyMsg ?? "");
    setQualClaims(saved.qualClaims ?? []);
    setQualMsg(saved.qualMsg ?? "");
    setDatasetResult(saved.datasetResult ?? null);
    setDatasetMsg(saved.datasetMsg ?? "");
    setDatasetComparison(saved.datasetComparison ?? null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditKey]);

  async function findDataset() {
    if (!paperText.trim()) { setDatasetMsg("No paper text loaded."); return; }
    setDatasetBusy(true); setDatasetMsg("Scanning paper for dataset links…"); setDatasetResult(null); setDatasetComparison(null);
    try {
      const res = await fetch("/api/audit/dataset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_text: paperText, doi: paper?.doi ?? "", title: paper?.title ?? "" }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as any;
        throw new Error(err?.detail ?? `API error ${res.status}`);
      }
      const result: DatasetResult = await res.json();
      setDatasetResult(result);
      let message = "";
      if (result.flag === "no_public_dataset") message = "No public dataset found — the paper does not link to any repository.";
      else if (result.flag === "browserbase_unavailable") message = "Dataset link found but Browserbase is not configured.";
      else if (result.flag === "no_data_files_found") message = "Repository found but no downloadable data files (CSV/XLSX) detected on the page.";
      else if (result.has_dataset) {
        const totalFiles = result.datasets.reduce((s, d) => s + d.files.length, 0);
        message = `Found ${result.links.length} repository link${result.links.length !== 1 ? "s" : ""}. ${totalFiles > 0 ? `${totalFiles} data file${totalFiles !== 1 ? "s" : ""} downloaded and summarized.` : "No data files could be downloaded."}`;
      }
      setDatasetMsg(message);
      persistNumerical({ datasetResult: result, datasetMsg: message });
    } catch (e: any) {
      setDatasetMsg(`Error: ${e.message}`);
    } finally {
      setDatasetBusy(false);
    }
  }

  async function compareDatasetWithPaper(file: DatasetFile) {
    if (!apiKey) { setDatasetMsg("Anthropic API key not configured."); return; }
    setComparingDataset(true); setDatasetComparison(null);

    const statSummary = Object.entries(file.stats)
      .map(([col, s]: [string, any]) => {
        if (s.type === "numeric") return `${col}: N=${s.n}, mean=${s.mean}, SD=${s.sd}, min=${s.min}, max=${s.max}`;
        const top = (s.top_values as [string, number][]).map(([v, c]) => `${v} (n=${c})`).join(", ");
        return `${col}: ${s.n_unique} unique values — ${top}`;
      })
      .join("\n");

    const prompt = `You are a research-integrity auditor. Compare dataset statistics against what the paper reports.

Dataset: ${file.rows} rows, ${file.columns.length} columns
${statSummary}

Paper text:
<paper>
${paperText.slice(0, 20000)}
</paper>

Return ONLY valid JSON (no markdown, no preamble):
{
  "matches": [{"item": "brief label", "paper": "what paper claims", "dataset": "what dataset shows"}],
  "discrepancies": [{"item": "brief label", "paper": "what paper claims", "dataset": "what dataset shows", "note": "explanation"}],
  "unverifiable": [{"item": "brief label", "reason": "why it can't be checked"}],
  "summary": "One sentence overall verdict."
}`;

    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          model: claudeModel,
          max_tokens: 2048,
          messages: [{ role: "user", content: prompt }],
        }),
      });
      const data = await res.json() as any;
      const text = data.content?.find((b: any) => b.type === "text")?.text ?? "{}";
      const parsed: ComparisonResult = JSON.parse(extractJson(text));
      const comparison = { file, result: parsed };
      setDatasetComparison(comparison);
      persistNumerical({ datasetComparison: comparison });
      setTimeout(() => comparisonRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    } catch (e: any) {
      setDatasetMsg(`Comparison error: ${e.message}`);
    } finally {
      setComparingDataset(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">

      {/* Page header — matches MethodsClaimsPage pattern */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 shrink-0"><Gauge className="size-5 text-primary" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <h2 className="text-base font-semibold">Numerical Consistency</h2>
                {paper ? (
                  <p className="text-xs text-muted-foreground truncate">
                    Auditing <span className="font-medium text-foreground">{paper.title || paper.id}</span> for internal numeric contradictions and dataset mismatches
                  </p>
                ) : <p className="text-xs text-amber-600">No paper ingested — go to the Ingest tab first.</p>}
              </div>
              {!paper && (
                <Button size="sm" variant="outline" onClick={() => setPage("ingest")}>
                  <Upload className="size-4 mr-1.5" />Go to Ingest
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>

      {/* 1. Internal Consistency */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 shrink-0"><Hash className="size-4 text-primary" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold">Internal Consistency</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Flags where numbers contradict each other — subgroup Ns, percentages, table vs prose, implausible values.
                </p>
              </div>
              <Button size="sm" onClick={runConsistency} disabled={consistencyBusy || !paperText}>
                {consistencyBusy ? <><Loader2 className="size-3.5 mr-1.5 animate-spin" />Analyzing…</> : <><Play className="size-3.5 mr-1.5" />Run check</>}
              </Button>
            </div>
          </div>
        </div>

        {(consistencyBusy || consistencyFlags !== null) && (
          <div className="mt-4 space-y-2 py-1">
            {CONSISTENCY_STEPS.map((step, i) => {
              const stepFlags = consistencyFlags?.filter(f =>
                step.type === "other"
                  ? !["n_sum_error","percentage_mismatch","table_text_discrepancy","implausible_value"].includes(f.type)
                  : f.type === step.type
              ) ?? [];
              const done = !consistencyBusy && consistencyFlags !== null;
              const active = consistencyBusy && i === consistencyStep;
              const pending = consistencyBusy && i !== consistencyStep;

              return (
                <div key={i}>
                  <div className={`flex items-start gap-2.5 transition-opacity duration-500 ${pending && i > consistencyStep ? "opacity-30" : pending ? "opacity-60" : "opacity-100"}`}>
                    <div className="shrink-0 mt-0.5">
                      {active && <Loader2 className="size-4 animate-spin text-primary" />}
                      {done && stepFlags.length === 0 && <CheckCircle2 className="size-4 text-emerald-500" />}
                      {done && stepFlags.length > 0 && <XCircle className="size-4 text-red-500" />}
                      {pending && <div className="size-4 rounded-full border-2 border-muted-foreground/30" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className={`text-sm ${active ? "font-medium" : done && stepFlags.length > 0 ? "font-medium text-red-700" : done ? "text-emerald-800" : "text-muted-foreground"}`}>
                          {step.label}
                        </span>
                        {done && stepFlags.length > 0 && (
                          <span className="text-xs text-red-600 font-medium shrink-0">
                            {stepFlags.length} issue{stepFlags.length !== 1 ? "s" : ""}
                          </span>
                        )}
                        {done && stepFlags.length === 0 && (
                          <span className="text-xs text-emerald-600 shrink-0">ok</span>
                        )}
                      </div>
                      <p className={`text-xs mt-0.5 ${done && stepFlags.length > 0 ? "text-red-600/80" : done && stepFlags.length === 0 ? "text-emerald-700/80" : "text-muted-foreground"}`}>
                        {done && consistencySummaries[step.type ?? ""]
                          ? consistencySummaries[step.type ?? ""]
                          : done ? step.passMsg : step.desc}
                      </p>
                    </div>
                  </div>

                  {done && stepFlags.length > 0 && (
                    <div className="ml-6 mt-2 space-y-2">
                      {stepFlags.map((flag, fi) => (
                        <div key={fi} className="space-y-0.5 border-l-2 border-red-200 pl-3">
                          <div className="flex items-center gap-1.5">
                            <Badge variant="outline" className={SEV_COLOR[flag.severity] + " text-[10px] px-1.5 py-0"}>{flag.severity}</Badge>
                          </div>
                          <p className="text-sm">{flag.description}</p>
                          {flag.excerpt && (
                            <p className="text-xs font-mono bg-muted px-2 py-1 rounded text-muted-foreground">"{flag.excerpt}"</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* 2. Qualitative Claims */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 shrink-0"><Quote className="size-4 text-primary" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold">Qualitative Claim Consistency</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Checks that words like "majority", "most", "few", "nearly all" actually match the numbers reported.
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={extractQualClaims} disabled={extractingQual}>
                {extractingQual ? <><Loader2 className="size-3.5 mr-1.5 animate-spin" />Checking…</> : <><Sparkles className="size-3.5 mr-1.5" />Extract &amp; check</>}
              </Button>
            </div>
          </div>
        </div>

        {qualMsg && (
          <p className={`mt-3 text-sm ${qualClaims.some(c => c.pass === false) ? "text-amber-600" : "text-muted-foreground"}`}>{qualMsg}</p>
        )}

        {qualClaims.length > 0 && (
          <div className="mt-3 space-y-2">
            {qualClaims.map(c => (
              <div key={c.id} className={`border rounded-lg p-3 space-y-1 ${c.pass === false ? "border-red-300 bg-red-50/50" : c.pass === true ? "border-emerald-200 bg-emerald-50/30" : ""}`}>
                <div className="flex items-start gap-2">
                  <div className="mt-0.5 shrink-0">
                    {c.pass === true && <CheckCircle2 className="size-4 text-emerald-500" />}
                    {c.pass === false && <XCircle className="size-4 text-red-500" />}
                    {c.pass === null && <AlertTriangle className="size-4 text-amber-500" />}
                  </div>
                  <div className="min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">{c.qualifier}</span>
                      {c.pct_label && <span className="text-xs text-muted-foreground">→ {c.pct_label}</span>}
                    </div>
                    <p className="text-sm text-muted-foreground italic">"{c.claim}"</p>
                    <p className={`text-xs ${c.pass === false ? "text-red-600 font-medium" : c.pass === true ? "text-emerald-700" : "text-muted-foreground"}`}>{c.finding}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 3. Numbers vs Dataset */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 shrink-0"><Database className="size-4 text-primary" /></div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold">Numbers vs Dataset</h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Finds public datasets linked in the paper (Zenodo, Dryad, OSF, etc.) and compares reported numbers against the actual data.
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={findDataset} disabled={datasetBusy}>
                {datasetBusy
                  ? <><Loader2 className="size-3.5 mr-1.5 animate-spin" />Searching…</>
                  : <><Sparkles className="size-3.5 mr-1.5" />Find &amp; verify</>}
              </Button>
            </div>
          </div>
        </div>

        {datasetMsg && (
          <div className={`mt-3 flex items-start gap-2 text-sm ${datasetResult?.flag === "no_public_dataset" ? "text-amber-600" : "text-muted-foreground"}`}>
            {datasetResult?.flag === "no_public_dataset" && <AlertTriangle className="size-4 mt-0.5 shrink-0" />}
            <span>{datasetMsg}</span>
          </div>
        )}

        {datasetResult?.flag === "no_public_dataset" && (
          <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50/50 p-3 text-sm text-amber-800">
            <strong>No public dataset</strong> — this paper does not link to any open repository. Raw data cannot be independently verified.
            {!datasetResult.has_availability_statement && (
              <span className="block mt-1 text-xs">No data availability statement detected either.</span>
            )}
          </div>
        )}

        {datasetResult && datasetResult.links.length > 0 && (
          <div className="mt-3 space-y-3">
            {datasetResult.links.map((link, i) => {
              const ds = datasetResult.datasets.find(d => d.link.url === link.url);
              return (
                <div key={i} className="border rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium bg-primary/10 text-primary px-2 py-0.5 rounded">{link.repository}</span>
                    {"accession" in link && <span className="text-xs font-mono bg-muted px-1.5 rounded">{link.accession}</span>}
                    <a href={link.url} target="_blank" rel="noreferrer" className="text-xs font-mono text-muted-foreground hover:underline truncate max-w-xs">{link.url}</a>
                  </div>

                  {ds && ds.files.length > 0 && (
                    <div className="space-y-2 pt-1">
                      {ds.files.map((file, fi) => (
                        <div key={fi} className="bg-muted/40 rounded-md p-2.5 space-y-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-xs text-muted-foreground font-mono truncate">{file.url.split("/").pop()}</div>
                            <div className="text-xs shrink-0">{file.rows.toLocaleString()} rows · {file.columns.length} cols</div>
                          </div>
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(file.stats).slice(0, 8).map(([col, s]: [string, any]) => (
                              <div key={col} className="text-[10px] border rounded px-1.5 py-0.5 bg-background">
                                <span className="font-medium">{col}</span>
                                {s.type === "numeric"
                                  ? <span className="text-muted-foreground"> μ={s.mean} σ={s.sd}</span>
                                  : <span className="text-muted-foreground"> {s.n_unique} vals</span>}
                              </div>
                            ))}
                            {Object.keys(file.stats).length > 8 && (
                              <div className="text-[10px] text-muted-foreground px-1.5 py-0.5">+{Object.keys(file.stats).length - 8} more</div>
                            )}
                          </div>
                          <Button
                            size="sm" variant="outline" className="h-7 text-xs w-full"
                            onClick={() => compareDatasetWithPaper(file)}
                            disabled={comparingDataset}
                          >
                            {comparingDataset ? <><Loader2 className="size-3 mr-1.5 animate-spin" />Comparing…</> : "Compare with paper numbers"}
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}

                  {ds && ds.files.length === 0 && ds.page_ok && (
                    <div className="text-xs text-muted-foreground space-y-1">
                      {ds.page_summary?.includes("Dryad") ? (
                        <>
                          <p>{ds.page_summary}</p>
                          <p className="text-amber-600">Dryad requires authentication for direct file downloads. Download the CSV manually from the Dryad page and upload it here to compare numbers.</p>
                        </>
                      ) : (
                        <p>Repository page loaded but no downloadable data files found.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {datasetComparison && (() => { // eslint-disable-line
          const { result } = datasetComparison;
          return (
            <div ref={comparisonRef} className="mt-4 border-t pt-4 space-y-3">
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Dataset comparison</div>

              {result.summary && (
                <div className={`flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
                  result.discrepancies?.length > 0
                    ? "bg-amber-50 border border-amber-200 text-amber-900"
                    : "bg-emerald-50 border border-emerald-200 text-emerald-900"
                }`}>
                  {result.discrepancies?.length > 0
                    ? <AlertTriangle className="size-4 mt-0.5 shrink-0 text-amber-500" />
                    : <CheckCircle2 className="size-4 mt-0.5 shrink-0 text-emerald-500" />}
                  <span>{result.summary}</span>
                </div>
              )}

              {result.matches?.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-emerald-700 flex items-center gap-1.5">
                    <CheckCircle2 className="size-3.5" /> Verified ({result.matches.length})
                  </div>
                  <div className="space-y-1">
                    {result.matches.map((m, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs py-1 border-b border-border/40 last:border-0">
                        <CheckCircle2 className="size-3.5 text-emerald-500 mt-0.5 shrink-0" />
                        <span className="font-medium text-foreground w-36 shrink-0">{m.item}</span>
                        <span className="text-muted-foreground flex-1">Paper: {m.paper} → Dataset: {m.dataset}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.discrepancies?.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-red-700 flex items-center gap-1.5">
                    <XCircle className="size-3.5" /> Discrepancies ({result.discrepancies.length})
                  </div>
                  <div className="space-y-1.5">
                    {result.discrepancies.map((d, i) => (
                      <div key={i} className="rounded-md border border-red-200 bg-red-50/60 px-3 py-2 space-y-0.5">
                        <div className="flex items-center gap-2 text-xs font-medium text-red-800">
                          <XCircle className="size-3.5 shrink-0" />{d.item}
                        </div>
                        <div className="text-xs text-red-700 pl-5">Paper: {d.paper} · Dataset: {d.dataset}</div>
                        {d.note && <div className="text-xs text-red-600/80 pl-5">{d.note}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.unverifiable?.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                    <AlertTriangle className="size-3.5" /> Cannot verify ({result.unverifiable.length})
                  </div>
                  <div className="space-y-0.5">
                    {result.unverifiable.map((u, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs py-0.5">
                        <span className="text-muted-foreground/60 mt-0.5">—</span>
                        <span className="text-muted-foreground"><span className="font-medium text-foreground">{u.item}</span>: {u.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })()}
      </Card>

    </div>
  );
}

export function ImagingPage() {
  return (
    <FeaturePlaceholder
      icon={ImageIcon}
      stage="Detect"
      title="Image Forensics"
      summary="Screen figures for manipulation: copy-move and splice detection, error-level analysis, duplicate/near-duplicate panels across the paper, and AI-generated-figure detection."
      inputs={["Extracted figures + their coordinate maps from Ingest"]}
      outputs={["Image-forensics flags with highlighted regions and similarity scores"]}
      reuses={[
        <>Figure extraction + coordinate map from Ingest</>,
        <>Redis vector store for figure embeddings (near-duplicate search)</>,
      ]}
      toBuild={[
        "image-forensics agent: OpenCV (copy-move, ELA), perceptual hashing, embedding model",
        "AI-generated-figure detector",
        "This is wholly new — the template is text-only",
      ]}
    />
  );
}

export function MethodsPage() {
  return (
    <FeaturePlaceholder
      icon={GitCompare}
      stage="Detect"
      title="Methods ↔ Claims"
      summary="Check whether the paper's conclusions are supported by what its methods and results actually show — flag over-claiming, mismatched test choices, and claims not backed by the reported data."
      inputs={["Methods, results, and conclusion/claim spans from Ingest"]}
      outputs={["Methods-vs-claim mismatch flags with the claim and the supporting (or missing) evidence"]}
      reuses={[
        <>LLM dispatcher with Claude for reasoning-heavy comparison</>,
        <>The criterion-agent decomposition pattern (<Code>CriterionAgent</Code>) in <Code>Backend/utils.py</Code></>,
        <>Evidence-popover UI from the screening pages</>,
      ]}
      toBuild={[
        "methods-claims agent",
        "claim ↔ evidence alignment with calibrated confidence",
      ]}
    />
  );
}

export function ReferencesPage() {
  return (
    <FeaturePlaceholder
      icon={BookMarked}
      stage="Detect"
      title="Reference Integrity"
      summary="Resolve every cited reference, verify it exists and supports the in-text claim, and flag retracted, mismatched, or non-existent citations."
      inputs={["Reference list + in-text citation contexts from Ingest"]}
      outputs={["Reference flags: unresolved, mismatched (citation-claim), or retracted references"]}
      reuses={[
        <>Crossref / Semantic Scholar / OpenAlex / Europe PMC resolution in <Code>Backend/data_services.py</Code></>,
        <>LLM dispatcher for citation-claim support checks</>,
      ]}
      toBuild={[
        "reference-integrity agent + citation-claim support check",
        "Retraction Watch check (via Crossref / Retraction Watch data)",
        "Browserbase fetch path for cited PDFs beyond the literature APIs",
      ]}
    />
  );
}

// ──────────────────────────────────────────────────────────────────
// Reliability
// ──────────────────────────────────────────────────────────────────

export function ReliabilityPage() {
  return (
    <FeaturePlaceholder
      icon={Gauge}
      stage="Reliability"
      title="Reliability Layer"
      summary="The differentiator. Per-flag confidence calibration with abstention, plus conclusion-impact triage that estimates whether each flag would change the paper's conclusions — then ranks flags by impact."
      inputs={["Raw flags from every detection agent", "Human accept/reject labels (to fit calibration)"]}
      outputs={["Calibrated per-flag confidence + abstain decisions", "Conclusion-impact score per flag", "A prioritized flag list (default UI shows only high-confidence flags)"]}
      reuses={[
        <>Confidence fields already on agent outputs; threshold logic in <Code>Backend/leads_screening.py</Code> as the starting hook</>,
        <>Stats engine in <Code>meta_analysis.py</Code> to re-derive downstream results for impact estimation</>,
      ]}
      toBuild={[
        "Per-flag calibration (Platt / isotonic) — note: NOT in the template; sklearn must be added (no calibration code exists today)",
        "Abstention policy",
        "conclusion-impact triage: re-derive each result and estimate conclusion change",
        "Terac labeling loop → fine-tune calibration on labels; Arize calibration curves + in-product self-benchmark",
      ]}
    />
  );
}

export function ReviewPage() {
  return (
    <FeaturePlaceholder
      icon={ShieldCheck}
      stage="Reliability"
      title="Flag Review"
      summary="The human-in-the-loop surface. Every flag is accept / dismiss / needs-human, with its evidence link and calibrated confidence. Framing is reviewer-assist, never automated accusation."
      inputs={["Calibrated, ranked flags", "The reviewer"]}
      outputs={["accept / dismiss / needs-human labels per flag", "Labels feed back into calibration (Terac)"]}
      reuses={[
        <>The per-item screening-decision UI in <Code>src/app/pages/AbstractPage.tsx</Code> and <Code>FullTextPage.tsx</Code> → becomes accept/dismiss/needs-human triage</>,
        <>Override state (<Code>abstractOverrides</Code> / <Code>fullTextOverrides</Code>) in the store → becomes per-flag decisions</>,
        <>Evidence popovers + sticky-table layout</>,
      ]}
      toBuild={[
        "Flag triage table keyed by flag (not paper), defaulting to high-confidence only",
        "Evidence link → jump to exact location/highlight in the document",
        "Terac integration to collect labels",
      ]}
    />
  );
}

// ──────────────────────────────────────────────────────────────────
// Report
// ──────────────────────────────────────────────────────────────────

export function ReportPage() {
  return (
    <FeaturePlaceholder
      icon={FileText}
      stage="Report"
      title="Audit Report"
      summary="The structured audit report: every confirmed flag with severity, calibrated confidence, conclusion-impact, and an evidence link — exported as PDF and JSON."
      inputs={["Reviewed + calibrated flags", "Paper metadata and versions"]}
      outputs={["Audit report (PDF)", "Machine-readable report (JSON)"]}
      reuses={[
        <>Export/reporting UI from <Code>src/app/components/PrismaFlow.tsx</Code> (SVG/PNG/PDF) and the <Code>docx</Code>-based Word export</>,
        <>Session snapshot as the JSON backbone</>,
      ]}
      toBuild={[
        "Audit-report template with severity / confidence / impact / evidence links",
        "JSON schema for the structured report",
        "Demo build around a paper whose error flips its conclusion",
      ]}
    />
  );
}
