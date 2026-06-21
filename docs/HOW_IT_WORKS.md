# AuData: How It Works

AuData is an AI research-integrity auditor for biomedical papers and preprints. You give it one paper; a team of detection agents recompute its statistics, cross-check its internal numbers, screen its figures for manipulation and reuse, test whether its conclusions are supported, and verify its citations. Every finding comes back with a severity, the evidence behind it, and a one-click jump to the exact spot in the source PDF.

The guiding principle is **reviewer assistance, not an automated verdict**. AuData surfaces leads with their evidence so a human can make a defensible call. It never accuses, ranks authors, or publishes a score.

---

## The big picture

**Flow:** Ingest a paper, run the detectors (individually or all at once), review the evidence-linked flags, and export a consolidated report.

**Architecture:**
- **Frontend** (React + Vite + Tailwind/shadcn). A keep-alive tab shell so switching tabs is instant and per-paper results persist across tab changes and refreshes.
- **Backend** (FastAPI, port 8010). A standalone service with paper ingest, the detection agents, persistence, and reporting.
- **Task-aware LLM router.** Heavy reasoning goes to Claude; extraction, vision, and embeddings run on local models via Ollama. Every model is env-overridable. Calls are cached.
- **Redis** powers the KV/response cache, semantic caching (LangCache), figure vector search (RediSearch KNN), and long-term agent memory.
- **Observability:** Sentry captures errors, performance traces (frontend-to-backend distributed), profiling, logs, and session replay.
- **Agent interfaces:** the auditor is exposed as a Band agent (agent-to-agent mesh) and a Fetch uAgent.

**Persistence.** Each detector's results are saved per paper (Redis + SQLite) and rehydrate automatically, so a paper you audited earlier reopens with all its findings intact.

**Evidence linking.** Wherever possible a finding carries a verbatim quote and a locator that opens the PDF highlighted on the exact statistic, figure, or reference.

---

## The tabs

### Dashboard (command center)
The hub for the paper under audit. Run every detector from one place with **Run all**, or run/re-run any single detector, watch progress, and see each detector's status (idle, running, clean, or flagged) with its flag count. From here you jump to the Audit Report. Running a detector here populates its tab and persists the result.

### Ingest
Brings a paper in four ways: upload a PDF, pull by DOI, search by name, or fetch any paper URL. It resolves clean metadata and pulls full text through an open-access ladder (Europe PMC, PMC, Unpaywall, arXiv), with **Browserbase** as a headless-browser fallback for hard-to-reach sources. It parses the PDF into sections, tables, and figures, and flags retraction status. Everything downstream reads from this one normalized paper object.

### Numerical Consistency
Checks the paper's internal numbers across **six checks**, each with its own subsection on the page:
- **Subgroup N sums** (do arm/group sizes add up to the total?)
- **Percentage vs counts** (does count / total match the stated percent?)
- **Table vs prose** (do the same numbers agree between tables and text?)
- **Implausible values** (means, SDs, ranges, or percentages that are impossible)
- **Abstract vs results** (do headline numbers match the body?)
- **Qualitative quantifiers** (does "most / majority / few" match the actual percentage?)

The overview at the top shows what each check found and is clickable: click a check to jump to its section. For every inconsistency you see the **numbers it used and where each came from** ("Pulled from the paper"), the **explicit arithmetic** that exposes the problem (reported vs should-be), the verbatim excerpt, and a Locate-in-PDF button. You can accept or dismiss each flag and export to CSV.

### Statistical Recompute
Two sub-views (toggle at the top):
- **Statistical recompute.** Finds reported statistical claims (t, F, chi-square, r paired with a p-value) and recomputes the p-value from the test statistic, flagging mismatches. A master-detail view shows each claim with a full breakdown: test type, the reported values, the formula, the substitution, the recomputed p, and the verdict. Locate jumps to the highlighted statistic in the PDF.
- **Meta-analysis recreation.** If the paper is a meta-analysis, it re-extracts the included studies and recomputes the pooled effect two ways (inverse-variance fixed effect and DerSimonian-Laird random effects), with I-squared / Q / tau-squared heterogeneity, a forest plot, and a step-by-step audit of every pooling calculation. It compares the recomputed pooled estimate against the paper's reported one and reports consistent vs discrepancy.

### Image Forensics
Extracts the figures from the PDF and screens them. It first classifies each figure as **photographic** (blots, gels, micrographs, photos) or **line-art** (schematics, flowcharts, plots); manipulation checks run only on photographic figures, because they produce false positives on diagrams. On photographic figures it runs:
- **Copy-move / clone detection** (repeated regions within a figure)
- **Splice detection** (inserted/pasted region boundaries, ignoring panel borders and axes)
- **ELA** (error-level analysis) as an inspection overlay
- **Cross-paper reuse** via perceptual hashing and CLIP-embedding similarity against other papers in your library (Redis vector search)
- A **local vision-model** integrity check (always on)

Results are a severity-sorted list of specific suspicious or matching aspects. Each card shows the actual figure with the suspicious region highlighted (or the two figures side by side for cross-paper reuse), a page locator, and a plain-language explanation. No opaque risk scores.

### Methods <-> Claims
Extracts the paper's claims and checks each against what the methods and results actually support, flagging over-claims, causal over-reach, over-generalization, unsupported statements, and methods mismatches. A master-detail view shows each claim with its verdict, the supporting (or missing) evidence, severity, and Locate-in-PDF. Accept/dismiss and CSV export included.

### Reference Integrity
Audits every reference: resolves each citation, verifies it exists and matches, and runs a **retraction check**. It also reports corpus-level metrics: self-citation rate, uncited-in-text references, duplicates, future-dated citations, the citation year range, and the most-cited reference. You can also paste your own reference list to audit without a full paper. Master-detail view, accept/dismiss, CSV export.

### Audit Report
A consolidated, read-only report across every detector for the study: a verdict banner, headline counts by severity, a detector-by-detector status grid, and the boxed findings with their evidence and severity. Exportable as a **Word document** or Markdown, with each finding carrying its severity, confidence, and evidence links, ready for a researcher, reviewer, or journal.

---

## Technology and sponsors

- **Anthropic Claude** for reasoning-heavy checks; **local Ollama models** (Qwen, MedGemma, a vision model, and an embedding model) for extraction, vision, and embeddings, chosen by the task-aware router.
- **Redis** as the backbone: response/KV cache, **LangCache** (semantic cache so paraphrased prompts reuse results), **RediSearch vector search** (cross-paper figure matching), and **native agent memory** (long-term reviewer-decision memory with KNN recall).
- **Browserbase** for headless paper fetching.
- **Sentry** for full observability (errors, tracing, profiling, logs, session replay).
- **Band** and **Fetch.ai uAgents** expose the auditor for agent-to-agent collaboration.

## Ethics in the design

AuData audits public papers, not personal data. It frames every flag as a reviewer-assist lead with its evidence, never an accusation. Deterministic checks (statistical recomputation, numerical validation, perceptual hashing, ELA) do much of the work, and a task-aware router plus semantic caching keep cloud LLM usage down. Keys stay server-side, error monitoring runs with PII disabled, and the whole pipeline can run on local models so unpublished manuscripts never leave the machine.
