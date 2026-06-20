// AuData — Biomedical Research-Integrity Auditor
// ------------------------------------------------------------------
// These are PLACEHOLDER pages, one per feature of the audit pipeline.
// Each carries the spec for the feature it will become: what it does,
// its inputs/outputs, which Evidence-Engine template modules it reuses,
// and what still needs to be built. We fill these in one feature at a
// time. The reusable scaffolding (LLM dispatcher, literature APIs,
// stats engine, session store, SSE streaming, decision/report UI) is
// kept intact in the backend and lib/ and is referenced below.

import { ReactNode } from "react";
import { Card } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import {
  LayoutDashboard, Upload, Calculator, Hash, Image as ImageIcon,
  GitCompare, BookMarked, Gauge, ShieldCheck, FileText, Users, Construction,
} from "lucide-react";

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

export function NumericalPage() {
  return (
    <FeaturePlaceholder
      icon={Hash}
      stage="Detect"
      title="Numerical Consistency"
      summary="Cross-check numbers within the paper for internal consistency: group Ns that don't sum to totals, percentages that don't match counts, means/SDs outside plausible ranges, table-vs-text disagreements."
      inputs={["Extracted numbers, tables, and their in-text references"]}
      outputs={["Consistency flags with the conflicting values and locations"]}
      reuses={[
        <>Table + number extraction from Ingest</>,
        <>LLM dispatcher for reconciliation reasoning</>,
        <>Per-flag triage UI</>,
      ]}
      toBuild={[
        "numerical-consistency agent (GRIM/GRIMMER-style checks + table↔text reconciliation)",
        "Rule library for arithmetic / proportion / range checks",
      ]}
    />
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
