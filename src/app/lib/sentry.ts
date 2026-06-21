// Frontend observability via Sentry: errors, performance tracing (distributed
// with the backend), and session replay. Active only when VITE_SENTRY_DSN is set.
// The DSN is public/client-safe by design. PII stays off; papers are public.
import * as Sentry from "@sentry/react";

export function initSentry() {
  const env = (import.meta as any)?.env || {};
  const dsn: string | undefined = env.VITE_SENTRY_DSN;
  if (!dsn) return;
  Sentry.init({
    dsn,
    environment: env.MODE || "development",
    release: "audata@0.1.0",
    sendDefaultPii: false,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({ maskAllText: false, blockAllMedia: false }),
    ],
    // Capture every transaction and every session replay for the demo.
    tracesSampleRate: 1.0,
    replaysSessionSampleRate: 1.0,
    replaysOnErrorSampleRate: 1.0,
    // Propagate the trace headers to the API so a click → request → detector run
    // shows up as one distributed trace across frontend and backend.
    tracePropagationTargets: ["localhost", /^\/api/, /^https?:\/\/localhost:8010/],
  });
  Sentry.setTag("service", "audata-frontend");
}
