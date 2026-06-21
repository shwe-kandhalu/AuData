// Sessions persist to AuData's own backend (SQLite), keyed by a per-browser
// owner id — no Supabase / Evidence Engine edge function involved.
import { apiConfig, clientSessionId } from "./apiClient";

async function af(path: string, init?: RequestInit): Promise<any> {
  const r = await fetch(`${apiConfig.baseUrl}${path}`, {
    headers: { "Content-Type": "application/json" }, ...init,
  });
  const t = await r.text();
  let j: any = null;
  try { j = t ? JSON.parse(t) : null; } catch { /* non-json */ }
  if (!r.ok) throw new Error(j?.detail || t || `Request failed (${r.status})`);
  return j;
}

export type SessionMeta = { id: string; title: string; updated_at: string; created_at: string };
// The session payload is whatever the store snapshot returns; kept loose so the
// AuData store can evolve its shape without touching this layer.
export type SessionData = Record<string, any>;

export async function listSessions(): Promise<SessionMeta[]> {
  const r = await af(`/sessions?owner=${encodeURIComponent(clientSessionId())}`);
  return r.sessions || [];
}
export async function loadSession(id: string): Promise<{ id: string; title: string; data: SessionData }> {
  const r = await af(`/sessions/${encodeURIComponent(id)}`);
  return r.session;
}
export async function saveSession(id: string, title: string, data: SessionData) {
  const r = await af(`/sessions/${encodeURIComponent(id)}`, {
    method: "PUT", body: JSON.stringify({ title, data, owner: clientSessionId() }),
  });
  return r.session;
}
export async function deleteSession(id: string) {
  await af(`/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function renameSession(id: string, title: string) {
  await af(`/sessions/${encodeURIComponent(id)}/title`, { method: "PATCH", body: JSON.stringify({ title }) });
}
