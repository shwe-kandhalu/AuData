#!/usr/bin/env bash
# =============================================================================
# AuData — one-shot, non-interactive installer + launcher
#
# Sets up an isolated environment for the app and runs it:
#   1. Installs system deps (Homebrew on macOS / apt on Linux): python, node, pnpm
#   2. Creates an isolated Backend Python venv (Backend/.venv) + installs requirements
#   3. Installs the frontend pnpm packages (node_modules)
#   4. Configures Backend/.env from .env.example (auto-fills ENTREZ_EMAIL from git)
#   5. (optional, --with-models) Installs Ollama + pulls local LLMs
#   6. Starts the FastAPI backend on :8010 and the Vite frontend on :5173
#      (override with BACKEND_PORT / FRONTEND_PORT env vars)
#   7. Health-checks both, prints the URLs
#
# Re-running is safe — every step is idempotent. To stop everything: ./teardown.sh
#
# By default the local Ollama models are NOT downloaded: AuData currently runs on
# placeholder pages and only needs an LLM once you build a detection feature (and
# even then a cloud key in Backend/.env works). Pass --with-models to pull them.
#
# Flags:
#   --with-models      Install Ollama and pull the local LLMs (~9 GB)
#   --no-start         Install everything but don't launch the services
#   --backend-only     Skip frontend
#   --frontend-only    Skip backend
#   -h | --help        Show this help
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(pwd)"

# ─── ports (override via env: BACKEND_PORT=8011 FRONTEND_PORT=5174 ./setup.sh) ─
# Defaults are chosen so AuData runs as its own app without clashing with other
# local services (e.g. a separate backend on :8000). Vite reads these too.
export BACKEND_PORT="${BACKEND_PORT:-8010}"
export FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# ─── color logging ──────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; DIM="\033[2m"; RESET="\033[0m"
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi
log()  { printf "${BOLD}${GREEN}==>${RESET} %s\n" "$*"; }
warn() { printf "${BOLD}${YELLOW}!!${RESET}  %s\n" "$*"; }
err()  { printf "${BOLD}${RED}xx${RESET}  %s\n" "$*" >&2; }
die()  { err "$@"; exit 1; }

# ─── args ───────────────────────────────────────────────────────────────────
WITH_MODELS=0
START_SERVICES=1
INSTALL_BACKEND=1
INSTALL_FRONTEND=1
for arg in "$@"; do
  case "$arg" in
    --with-models)      WITH_MODELS=1 ;;
    --no-start)         START_SERVICES=0 ;;
    --backend-only)     INSTALL_FRONTEND=0 ;;
    --frontend-only)    INSTALL_BACKEND=0 ;;
    -h|--help)          sed -n '/^# Sets up/,/^# ====/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown argument: $arg  (try --help)" ;;
  esac
done

# ─── OS detect ──────────────────────────────────────────────────────────────
OS=""
case "$(uname -s)" in
  Darwin*) OS=mac ;;
  Linux*)  OS=linux ;;
  *) die "Unsupported OS: $(uname -s). Only macOS and Linux are auto-supported." ;;
esac
log "Detected OS: $OS"

# ─── 1. system dependencies ─────────────────────────────────────────────────
install_mac_deps() {
  if ! command -v brew >/dev/null 2>&1; then
    log "Installing Homebrew (non-interactive)…"
    NONINTERACTIVE=1 /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
    if [ -x /usr/local/bin/brew ];   then eval "$(/usr/local/bin/brew shellenv)"; fi
  fi

  local pkgs=()
  # Pin a Python the requirements actually have wheels for (numpy 1.26.4 /
  # pydantic 2.9 do not ship 3.13 wheels). python@3.12 is the safe default.
  command -v python3.12 >/dev/null 2>&1 || command -v python3.11 >/dev/null 2>&1 || pkgs+=("python@3.12")
  if [ "$INSTALL_FRONTEND" = 1 ]; then
    command -v node >/dev/null 2>&1 || pkgs+=("node")
    command -v pnpm >/dev/null 2>&1 || pkgs+=("pnpm")
  fi
  if [ "$WITH_MODELS" = 1 ]; then
    command -v ollama >/dev/null 2>&1 || pkgs+=("ollama")
  fi

  if [ "${#pkgs[@]}" -gt 0 ]; then
    log "Installing via Homebrew: ${pkgs[*]}"
    brew install "${pkgs[@]}"
  else
    log "All required system dependencies already installed."
  fi
}

install_linux_deps() {
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing system packages via apt…"
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip python3-venv curl ca-certificates
    if [ "$INSTALL_FRONTEND" = 1 ] && ! command -v node >/dev/null 2>&1; then
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
      sudo apt-get install -y -qq nodejs
    fi
    if [ "$INSTALL_FRONTEND" = 1 ] && ! command -v pnpm >/dev/null 2>&1; then
      sudo npm install -g pnpm
    fi
    if [ "$WITH_MODELS" = 1 ] && ! command -v ollama >/dev/null 2>&1; then
      log "Installing Ollama (will run with sudo)…"
      curl -fsSL https://ollama.com/install.sh | sh
    fi
  else
    die "Linux: only apt is auto-supported. Install python3, node, pnpm manually, then re-run."
  fi
}

if [ "$OS" = mac ]; then
  install_mac_deps
else
  install_linux_deps
fi

# Pick the best available Python interpreter for the venv.
PYTHON_BIN=""
for cand in python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PYTHON_BIN="$cand"; break; fi
done
[ -n "$PYTHON_BIN" ] || die "No python3 found after install attempt."
if [ "$INSTALL_FRONTEND" = 1 ]; then
  command -v pnpm >/dev/null 2>&1 || die "pnpm still missing after install attempt."
fi

PY_VER="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
log "Using interpreter: $PYTHON_BIN (Python $PY_VER)"
case "$PY_VER" in
  3.12|3.11|3.10) ;;
  *) warn "Python $PY_VER is outside the tested 3.10–3.12 range; numpy/pydantic wheels may be missing and pip may try to build from source." ;;
esac

# ─── 2. backend (isolated Python venv + deps) ───────────────────────────────
if [ "$INSTALL_BACKEND" = 1 ]; then
  log "Setting up isolated Backend Python venv (Backend/.venv)…"
  (
    cd "$REPO_ROOT/Backend"
    if [ ! -d .venv ]; then
      "$PYTHON_BIN" -m venv .venv
    fi
    # shellcheck source=/dev/null
    source .venv/bin/activate
    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    deactivate
  )
  log "Backend dependencies installed."

  if [ ! -f "$REPO_ROOT/Backend/.env" ]; then
    log "Creating Backend/.env from .env.example"
    cp "$REPO_ROOT/Backend/.env.example" "$REPO_ROOT/Backend/.env"
    GIT_EMAIL="$(git config --get user.email 2>/dev/null || true)"
    if [ -n "${GIT_EMAIL:-}" ]; then
      if sed --version >/dev/null 2>&1; then
        sed -i "s|^ENTREZ_EMAIL=.*|ENTREZ_EMAIL=$GIT_EMAIL|" "$REPO_ROOT/Backend/.env"
      else
        sed -i '' "s|^ENTREZ_EMAIL=.*|ENTREZ_EMAIL=$GIT_EMAIL|" "$REPO_ROOT/Backend/.env"
      fi
      log "Set ENTREZ_EMAIL=$GIT_EMAIL  (from git config)"
    else
      warn "git user.email not set — leaving ENTREZ_EMAIL placeholder in Backend/.env."
    fi
    # Without --with-models there's no local LLM; default to no model so a bare
    # backend boots cleanly. Add a cloud key + pick a model in the UI to enable AI.
    if [ "$WITH_MODELS" = 0 ]; then
      if sed --version >/dev/null 2>&1; then
        sed -i "s|^DEFAULT_MODEL=.*|DEFAULT_MODEL=|" "$REPO_ROOT/Backend/.env"
      else
        sed -i '' "s|^DEFAULT_MODEL=.*|DEFAULT_MODEL=|" "$REPO_ROOT/Backend/.env"
      fi
    fi
  else
    log "Backend/.env already exists — leaving as-is."
  fi
fi

# ─── 3. frontend (pnpm) ─────────────────────────────────────────────────────
if [ "$INSTALL_FRONTEND" = 1 ]; then
  log "Installing frontend dependencies (pnpm)…"
  pnpm install --silent
fi

# ─── 4 & 5. Ollama + local models (opt-in) ──────────────────────────────────
LEADS_TAG="hf.co/mradermacher/leads-mistral-7b-v1-GGUF:latest"
THINKING_TAG="qwen2.5:7b"

have_model() { ollama list 2>/dev/null | awk '{print $1}' | grep -Fxq "$1"; }

ensure_ollama_running() {
  if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    log "Ollama already running."; return
  fi
  log "Starting Ollama…"
  if [ "$OS" = mac ] && command -v brew >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || true
  fi
  sleep 1
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    mkdir -p "$REPO_ROOT/.runtime"
    nohup ollama serve >"$REPO_ROOT/.runtime/ollama.log" 2>&1 &
    echo $! > "$REPO_ROOT/.runtime/ollama.pid"
  fi
  for _ in $(seq 1 20); do
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      log "Ollama is up on :11434."; return
    fi
    sleep 1
  done
  warn "Ollama did not come up within 20 s. Check ${REPO_ROOT}/.runtime/ollama.log"
}

if [ "$WITH_MODELS" = 1 ]; then
  command -v ollama >/dev/null 2>&1 || die "ollama missing despite --with-models."
  ensure_ollama_running
  if have_model "$LEADS_TAG"; then log "LEADS-Mistral 7B already pulled."
  else log "Pulling LEADS-Mistral 7B (~4 GB)…"; ollama pull "$LEADS_TAG"; fi
  if have_model "$THINKING_TAG"; then log "Qwen 2.5 7B already pulled."
  else log "Pulling Qwen 2.5 7B (~5 GB)…"; ollama pull "$THINKING_TAG"; fi
else
  log "Skipping Ollama + local models (run with --with-models to enable local LLMs)."
fi

# ─── 6. start backend + frontend ────────────────────────────────────────────
mkdir -p "$REPO_ROOT/.runtime"

wait_for_url() {
  local url="$1"; local label="$2"; local timeout="${3:-30}"
  for _ in $(seq 1 "$timeout"); do
    if curl -sf "$url" >/dev/null 2>&1; then log "$label is ready."; return 0; fi
    sleep 1
  done
  warn "$label did not come up within ${timeout}s."; return 1
}

port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

if [ "$START_SERVICES" = 1 ]; then
  if [ "$INSTALL_BACKEND" = 1 ]; then
    if port_in_use "$BACKEND_PORT"; then
      log "Port $BACKEND_PORT already in use — assuming AuData backend is already running."
    else
      log "Starting backend (FastAPI) on :${BACKEND_PORT} ..."
      (
        cd "$REPO_ROOT/Backend"
        # shellcheck source=/dev/null
        source .venv/bin/activate
        nohup uvicorn api:app --host 0.0.0.0 --port "$BACKEND_PORT" \
          >"$REPO_ROOT/.runtime/backend.log" 2>&1 &
        echo $! > "$REPO_ROOT/.runtime/backend.pid"
      )
      wait_for_url "http://localhost:$BACKEND_PORT/api/health" "Backend" 40 || \
        warn "Backend health check failed — see .runtime/backend.log"
    fi
  fi

  if [ "$INSTALL_FRONTEND" = 1 ]; then
    if port_in_use "$FRONTEND_PORT"; then
      log "Port $FRONTEND_PORT already in use — assuming AuData frontend is already running."
    else
      log "Starting frontend (Vite) on :${FRONTEND_PORT} ..."
      nohup pnpm dev --host >"$REPO_ROOT/.runtime/frontend.log" 2>&1 &
      echo $! > "$REPO_ROOT/.runtime/frontend.pid"
      wait_for_url "http://localhost:$FRONTEND_PORT" "Frontend" 30 || \
        warn "Frontend did not respond — see .runtime/frontend.log"
    fi
  fi
fi

# ─── 7. summary ─────────────────────────────────────────────────────────────
echo
log "Setup complete."
echo
echo -e "${BOLD}URLs${RESET}"
echo "  Frontend:    http://localhost:$FRONTEND_PORT"
echo "  Backend API: http://localhost:$BACKEND_PORT"
echo "  API docs:    http://localhost:$BACKEND_PORT/docs"
echo "  Health:      http://localhost:$BACKEND_PORT/api/health"
echo
if [ "$WITH_MODELS" = 1 ]; then
  echo -e "${BOLD}Local models (Ollama)${RESET}"
  have_model "$LEADS_TAG"    2>/dev/null && echo "  LEADS-Mistral 7B  (screening)"    || warn "  LEADS-Mistral 7B  — NOT pulled"
  have_model "$THINKING_TAG" 2>/dev/null && echo "  Qwen 2.5 7B       (reasoning)"     || warn "  Qwen 2.5 7B       — NOT pulled"
  echo
fi
if [ "$START_SERVICES" = 1 ]; then
  echo -e "${BOLD}Service logs${RESET}"
  [ -f "$REPO_ROOT/.runtime/backend.log" ]   && echo "  Backend:   $REPO_ROOT/.runtime/backend.log"
  [ -f "$REPO_ROOT/.runtime/frontend.log" ]  && echo "  Frontend:  $REPO_ROOT/.runtime/frontend.log"
  [ -f "$REPO_ROOT/.runtime/ollama.log" ]    && echo "  Ollama:    $REPO_ROOT/.runtime/ollama.log"
  echo
  echo -e "${BOLD}To stop everything${RESET}"
  echo "  ./teardown.sh"
fi
echo
echo -e "${DIM}To enable AI: add ANTHROPIC_API_KEY=… (or OPENAI_API_KEY=… / GEMINI_API_KEY=…)${RESET}"
echo -e "${DIM}to Backend/.env and pick the model in the sidebar — or rerun ./setup.sh --with-models${RESET}"
echo -e "${DIM}for local Ollama models.${RESET}"
