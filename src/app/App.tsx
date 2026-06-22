import { Component, ReactNode, useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { Toaster } from "./components/ui/sonner";
import { StoreProvider, useStore } from "./lib/store";
import { AuthProvider } from "./lib/auth";
import { UserMenu } from "./components/UserMenu";
import { NumericalPage } from "./pages/NumericalPage";
import { DashboardPage } from "./pages/DashboardPage";
import { AuditsPage } from "./pages/AuditsPage";
import { IngestPage } from "./pages/IngestPage";
import { ReferenceIntegrityPage } from "./pages/ReferenceIntegrityPage";
import { MethodsClaimsPage } from "./pages/MethodsClaimsPage";
import { ImageForensicsPage } from "./pages/ImageForensicsPage";
import { IngestService, AuditStore } from "./lib/apiClient";
import { RecomputePage } from "./pages/RecomputePage";
import { ReportPage } from "./pages/ReportPage";
import { LandingPage } from "./pages/LandingPage";
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
  report: { title: "Audit Report", subtitle: "Consolidated findings across every detector for this study", icon: FileText },
};

function Shell() {
  const s = useStore();
  const meta = PAGE_META[s.page];
  const Icon = meta.icon;

  // Keep-alive routing: mount each page the first time it is visited, then keep
  // it mounted and just toggle visibility. Switching tabs becomes instant (no
  // remount, no re-fetch, no re-render of big lists) and per-tab state survives.
  const [visited, setVisited] = useState<Set<string>>(() => new Set([s.page]));
  useEffect(() => {
    setVisited((prev) => (prev.has(s.page) ? prev : new Set(prev).add(s.page)));
  }, [s.page]);
  const PAGES: { id: string; node: ReactNode }[] = [
    { id: "dashboard", node: <DashboardPage /> },
    { id: "audits", node: <AuditsPage /> },
    { id: "ingest", node: <IngestPage /> },
    { id: "recompute", node: <RecomputePage /> },
    { id: "numerical", node: <NumericalPage /> },
    { id: "imaging", node: <ImageForensicsPage /> },
    { id: "methods", node: <MethodsClaimsPage /> },
    { id: "references", node: <ReferenceIntegrityPage /> },
    { id: "report", node: <ReportPage /> },
  ];
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

  // Whenever the paper under audit changes (open / restore), pull ALL of its
  // saved detection results from the server so every tab (incl. Dashboard)
  // shows them without having to visit each detector first.
  const paperId = s.paperUnderAudit?.id;
  useEffect(() => {
    if (!paperId) return;
    let cancelled = false;
    AuditStore.getAll(paperId).then((a) => {
      if (cancelled) return;
      if (a.references && !s.refAudits[paperId]) s.setRefAudits({ ...s.refAudits, [paperId]: a.references });
      if (a.methods && !s.methodsAudits[paperId]) s.setMethodsAudits({ ...s.methodsAudits, [paperId]: a.methods });
      if (a.meta && !s.metaAudits[paperId]) s.setMetaAudits({ ...s.metaAudits, [paperId]: a.meta });
      if (a.images && !s.imageAudits[paperId]) s.setImageAudits({ ...s.imageAudits, [paperId]: a.images });
      if (a.numerical && !s.numericalAudits[paperId]) s.setNumericalAudits({ ...s.numericalAudits, [paperId]: a.numerical });
      if (a.statcheck && !s.statcheckAudits[paperId]) s.setStatcheckAudits({ ...s.statcheckAudits, [paperId]: a.statcheck });
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId]);
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Toaster richColors position="top-right" />
      <Sidebar />
      <main className="flex-1 overflow-x-clip">
        <header className="border-b bg-card/50 backdrop-blur sticky top-0 z-20 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center gap-3">
            <Icon className="size-6 text-primary" />
            <div className="flex-1 min-w-0">
              <h1>{meta.title}</h1>
              <p className="text-sm text-muted-foreground truncate">
                {s.paperUnderAudit && !["dashboard", "audits", "ingest"].includes(s.page)
                  ? (s.paperUnderAudit.title || s.paperUnderAudit.id)
                  : meta.subtitle}
              </p>
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
          {PAGES.map(({ id, node }) =>
            visited.has(id) ? (
              <div key={id} className={s.page === id ? "" : "hidden"}>{node}</div>
            ) : null,
          )}
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
  const [showLanding, setShowLanding] = useState(true);
  return (
    <ErrorBoundary>
      <AuthProvider>
        <StoreProvider>
          {showLanding ? (
            <LandingPage onEnter={() => setShowLanding(false)} />
          ) : (
            <Shell />
          )}
        </StoreProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}
