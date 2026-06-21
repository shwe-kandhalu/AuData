import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";
import App from "./app/App.tsx";
import { initSentry } from "./app/lib/sentry";
import "./styles/index.css";

initSentry();

createRoot(document.getElementById("root")!).render(
  <Sentry.ErrorBoundary fallback={<p style={{ padding: 24 }}>Something went wrong. The error has been reported.</p>}>
    <App />
  </Sentry.ErrorBoundary>,
);
