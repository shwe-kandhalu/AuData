"""AuData settings — read straight from the environment.

Self-contained so the AuData service does not import Evidence Engine's config.
Loads Backend/.env (same file EE uses for keys), but only the values AuData needs.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# Identity / polite-pool email for Crossref / OpenAlex / Unpaywall.
ENTREZ_EMAIL = os.getenv("ENTREZ_EMAIL", "research@audata.local")

# Browserbase (headless-browser fetch).
BROWSERBASE_API_KEY = os.getenv("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT_ID = os.getenv("BROWSERBASE_PROJECT_ID", "")

# Redis (short-term session storage / cache). Set REDIS_URL to connect:
#   rediss://default:<password>@<host>:<port>
REDIS_URL = os.getenv("REDIS_URL", "")
SESSION_TTL_SECONDS = int(os.getenv("AUDATA_SESSION_TTL", "86400"))  # 24h

# Long-term store: SQLite file, separate from EE's Supabase.
AUDATA_DB_PATH = os.getenv("AUDATA_DB_PATH", "audata.db")

# Ollama (for the sidebar model list; AuData ingest itself needs no LLM).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Extra CORS origins (comma-separated); Vite dev on 5173 is allowed by default.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
