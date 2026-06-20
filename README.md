# AuData — Biomedical Research-Integrity Auditor

AuData audits a **single paper or preprint** for statistical errors, numerical
inconsistencies, figure manipulation, methods-vs-claim mismatches, and
citation/reference problems — then surfaces **prioritized, calibrated,
evidence-linked flags** through a human review surface. The framing is
**reviewer-assist, never automated accusation**: a human stays in the loop on
every flag.

AuData is built on the **Evidence Engine** systematic-review platform as a
template. The reusable parts (LLM dispatcher, literature APIs, statistics
engine, session store, SSE streaming, decision/report UI) are kept intact; the
review workflow is repurposed into an audit pipeline.

## Audit pipeline

```
Manage → Ingest → Detect → Reliability → Report
```

Each tab in the app is currently a **placeholder** carrying the spec for the
feature it will become (inputs, outputs, the template modules it reuses, and
what's left to build). We build them one at a time.

| Stage | Tab | Feature |
|-------|-----|---------|
| Manage | Dashboard | Pipeline overview |
| Manage | Audits | Paper-under-audit projects, versions, shared review |
| Ingest | Ingest | Parse structure, stats, tables, figures, references; version diff |
| Detect | Statistical Recompute | Recompute reported statistics, flag mismatches |
| Detect | Numerical Consistency | Internal-number / total / percentage / table checks |
| Detect | Image Forensics | Figure manipulation, duplication, AI-generation |
| Detect | Methods ↔ Claims | Conclusions vs. methods/results support |
| Detect | Reference Integrity | Resolve, verify, retraction-check citations |
| Reliability | Reliability Layer | Per-flag calibration, abstention, conclusion-impact triage |
| Reliability | Flag Review | Human-in-the-loop accept / dismiss / needs-human |
| Report | Audit Report | Structured report (PDF + JSON) with severity/confidence/evidence |

## Reuse / Adapt / Add (against the actual codebase)

**Reuse directly**
- **LLM dispatcher** — `AIService.get_model*` in `Backend/utils.py` (provider-agnostic: Claude, OpenAI, Gemini, Ollama via LangChain).
- **Literature APIs** — `Backend/data_services.py` (Crossref, Semantic Scholar, OpenAlex, Europe PMC, PubMed, arXiv/bioRxiv/medRxiv, …) for citation resolution, reference checks, and version fetch.
- **Statistics engine** — `Backend/meta_analysis.py` (pure-numpy effect sizes, pooling, heterogeneity, Egger/Begg, etc.) for stats-recompute.
- **Frontend shell + SSE + decision UI** — `src/app/` session store, the `/api/simulation/agentic/stream` SSE pattern, and the screening-decision table → per-flag triage.

**Adapt**
- Extraction service (`AITableExtractor`, `/api/extract/text`) → extractor of reported stats / Ns / claims.
- Session model (PICO, papers, decisions, extractions) → (paper-under-audit + versions, flags, decisions, labels).
- Supabase KV store (`supabase/`) → extend namespaces with flags, labels, versions, reports.
- PRISMA/export UI (`PrismaFlow.tsx`, `docx`) → structured audit report.

**Add (new builds — not present in the template)**
- Detection agents: stats-recompute, numerical-consistency, image-forensics, methods-claims, reference-integrity.
- **Reliability layer**: per-flag calibration (Platt/isotonic — note: *no* calibration code or sklearn exists in the template yet) + abstention + conclusion-impact triage.
- Full-PDF parsing (GROBID + PyMuPDF), figure + coordinate maps, table parsing (pdfplumber/Camelot).
- Image forensics (OpenCV / ELA / perceptual hashing / embeddings / AI-figure detection).
- Recompute sandbox (E2B / Modal), scipy/statsmodels.
- Retraction Watch checks + preprint version diff.
- Sponsor integrations: Fetch uAgents, Redis (vector/memory/cache/queue), Terac (labeling + calibration fine-tune), Arize (tracing/evals/calibration curves), Browserbase (web fetch), Sentry (errors).

## Stack

- **Frontend**: React + TypeScript + Vite, shadcn/Radix + Tailwind, REST + SSE.
- **Backend**: a standalone AuData FastAPI service (`Backend/audata/`), separate from the legacy Evidence Engine app (`Backend/api.py`).
- **LLM serving**: Ollama local models + cloud (Claude/GPT/Gemini) for reasoning-heavy steps.
- **Storage**: Redis for short-term session storage/cache (set `REDIS_URL`; falls back to in-memory if unset), SQLite for long-term persistence (`Backend/audata.db`) — both separate from Evidence Engine's Supabase. Browserbase for web fetch; biomedical literature APIs (Crossref/OpenAlex/Unpaywall/…).

## Quick start

One command installs an isolated environment (Backend Python venv + frontend
`node_modules`), configures `Backend/.env`, and launches both services:

```bash
./setup.sh                 # frontend :5173, backend :8010 (health-checked)
./setup.sh --with-models   # also install Ollama + pull local LLMs (~9 GB)
./teardown.sh              # stop everything it started
```

- Open **http://localhost:5173**. API docs at **http://localhost:8010/docs**.
- Re-running `./setup.sh` is idempotent. Override ports with
  `BACKEND_PORT=8011 FRONTEND_PORT=5174 ./setup.sh`.
- Local LLMs are **opt-in** — the placeholder app runs without them. To enable
  AI, either add a cloud key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
  `GEMINI_API_KEY`) to `Backend/.env` and pick the model in the sidebar, or run
  `./setup.sh --with-models`.

## Develop (manual)

```bash
# Frontend
pnpm install
pnpm dev          # Vite dev server (http://localhost:5173 → proxies /api to :8010)
pnpm typecheck
pnpm build

# Backend — the AuData service (in its venv)
cd Backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn audata.main:app --port 8010
```

Copy `Backend/.env.example` → `Backend/.env` and fill what you need: `ENTREZ_EMAIL`
(polite pool for Crossref/OpenAlex/Unpaywall), `BROWSERBASE_API_KEY` /
`BROWSERBASE_PROJECT_ID` (URL fetch), `REDIS_URL` (short-term storage; optional —
falls back to in-memory), and a model key (`ANTHROPIC_API_KEY` / …) for AI steps.

The legacy Evidence Engine FastAPI app still lives at `Backend/api.py` for
reference but is **not** started by AuData.
