import { Component, ReactNode, useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { Toaster } from "./components/ui/sonner";
import { StoreProvider, useStore } from "./lib/store";
import { AuthProvider } from "./lib/auth";
import { UserMenu } from "./components/UserMenu";
import {
  NumericalPage,
  ReliabilityPage, ReviewPage, ReportPage,
} from "./pages/AuditPlaceholders";
import { DashboardPage } from "./pages/DashboardPage";
import { AuditsPage } from "./pages/AuditsPage";
import { IngestPage } from "./pages/IngestPage";
import { ReferenceIntegrityPage } from "./pages/ReferenceIntegrityPage";
import { MethodsClaimsPage } from "./pages/MethodsClaimsPage";
import { ImageForensicsPage } from "./pages/ImageForensicsPage";
import { IngestService } from "./lib/apiClient";
import { RecomputePage } from "./pages/RecomputePage";
import { LayoutDashboard, Upload, Calculator, Hash, Image as ImageIcon, GitCompare, BookMarked, Gauge, ShieldCheck, FileText, Users } from "lucide-react";

const PAGE_META: Record<string, { title: string; subtitle: string; icon: any }> = {
  dashboard: { title: "AuData", subtitle: "Biomedical research-integrity auditor — overview", icon: LayoutDashboard },
  audits: { title: "Audits", subtitle: "Manage paper-under-audit projects, versions, and shared review", icon: Users },
  ingest: { title: "Ingest", subtitle: "Parse the paper: structure, statistics, tables, figures, references, versions", icon: Upload },
  recompute: { title: "Statistical Recompute", subtitle: "Recompute reported statistics and flag mismatches", icon: Calculator },
  numerical: { title: "Numerical Consistency", subtitle: "Cross-check internal numbers, totals, percentages, and tables", icon: Hash },
  imaging: { title: "Image Forensics", subtitle: "Screen figures for manipulation, duplication, and AI generation", icon: ImageIcon },
  methods: { title: "Methods ↔ Claims", subtitle: "Check that conclusions are supported by methods and results", icon: GitCompare },
  references: { title: "Reference Integrity", subtitle: "Resolve, verify, and retraction-check citations", icon: BookMarked },
  reliability: { title: "Reliability Layer", subtitle: "Per-flag calibration, abstention, and conclusion-impact triage", icon: Gauge },
  review: { title: "Flag Review", subtitle: "Human-in-the-loop accept / dismiss / needs-human triage", icon: ShieldCheck },
  report: { title: "Audit Report", subtitle: "Structured audit report with severity, confidence, and evidence links", icon: FileText },
};

function Shell() {
  const s = useStore();
  const meta = PAGE_META[s.page];
  const Icon = meta.icon;
  // If we landed on a /?invite=TOKEN URL, route to the Audits page so the
  // user sees the accept-invite banner. AuditsPage owns the actual accept flow.
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("invite") && s.page !== "audits") {
      s.setPage("audits");
    }
    // We only want this to run once on mount; the audits page handles
    // subsequent state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // On load, if no paper is in the store yet, restore the last one from the
  // server session (Redis) — so a refresh on any tab brings the paper back.
  useEffect(() => {
    if (s.paperUnderAudit) return;
    IngestService.restoreSession().then((p) => { if (p) s.setPaperUnderAudit(p); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Toaster richColors position="top-right" />
      <Sidebar />
      <main className="flex-1 overflow-x-clip">
        <header className="border-b bg-card/50 backdrop-blur sticky top-0 z-20 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center gap-3">
            <Icon className="size-6 text-primary" />
            <div className="flex-1">
              <h1>{meta.title}</h1>
              <p className="text-sm text-muted-foreground">{meta.subtitle}</p>
            </div>
            {s.currentProjectId && (
              <button
                onClick={() => s.setPage("audits")}
                className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md bg-primary/10 border border-primary/30 text-xs hover:bg-primary/20 transition-colors"
                title="Open audit settings"
              >
                <Users className="size-3.5 text-primary" />
                <span className="font-medium truncate max-w-[200px]">{s.currentProjectName || "Audit"}</span>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground">{s.currentProjectMode}</span>
                <span className="text-muted-foreground">·</span>
                <span className="text-muted-foreground">{s.currentProjectRole}</span>
              </button>
            )}
            <UserMenu />
          </div>
        </header>
        <div className="max-w-6xl mx-auto p-6">
          {s.page === "dashboard" && <DashboardPage />}
          {s.page === "audits" && <AuditsPage />}
          {s.page === "ingest" && <IngestPage />}
          {s.page === "recompute" && <RecomputePage />}
          {s.page === "numerical" && <NumericalPage />}
          {s.page === "imaging" && <ImageForensicsPage />}
          {s.page === "methods" && <MethodsClaimsPage />}
          {s.page === "references" && <ReferenceIntegrityPage />}
          {s.page === "reliability" && <ReliabilityPage />}
          {s.page === "review" && <ReviewPage />}
          {s.page === "report" && <ReportPage />}
        </div>
      </main>
    </div>
  );
}

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: any) { console.error("App error:", error, info); }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-background text-foreground">
          <div className="max-w-md space-y-2">
            <h2>Something went wrong</h2>
            <pre className="text-xs bg-muted p-3 rounded whitespace-pre-wrap">{this.state.error.message}</pre>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <StoreProvider>
          <Shell />
        </StoreProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
