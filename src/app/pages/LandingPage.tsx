import { useEffect, useRef, useState } from "react";
import { Hash, GitCompare, BookMarked, Calculator, Image as ImageIcon, ArrowRight } from "lucide-react";
import { Button } from "../components/ui/button";

const AUDITORS = [
  { icon: Calculator,   label: "Statistical Recompute" },
  { icon: Hash,         label: "Numerical Consistency" },
  { icon: GitCompare,   label: "Methods ↔ Claims" },
  { icon: BookMarked,   label: "Reference Integrity" },
  { icon: ImageIcon,    label: "Image Forensics" },
];

const STATS = [
  { value: "5",   label: "auditors" },
  { value: "12",  label: "check types" },
  { value: "0",   label: "false positives tolerated" },
];

export function LandingPage({ onEnter }: { onEnter: () => void }) {
  const spotRef   = useRef<HTMLDivElement>(null);
  const [activeChip, setActiveChip] = useState(0);

  // Cursor spotlight
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (spotRef.current) {
        spotRef.current.style.left = `${e.clientX}px`;
        spotRef.current.style.top  = `${e.clientY}px`;
      }
    };
    window.addEventListener("mousemove", move);
    return () => window.removeEventListener("mousemove", move);
  }, []);

  // Enter key → start
  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.key === "Enter") onEnter(); };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
  }, [onEnter]);

  // Cycle active chip
  useEffect(() => {
    const id = setInterval(() => setActiveChip(p => (p + 1) % AUDITORS.length), 1400);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col overflow-hidden relative select-none">

      <style>{`
        @keyframes cardIn {
          from { opacity: 0; transform: translateY(10px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .auditor-card {
          opacity: 0;
          animation: cardIn 0.35s ease-out forwards;
        }
        @keyframes arrowPulse {
          0%, 100% { transform: translateX(0); }
          50%       { transform: translateX(3px); }
        }
        .arrow-pulse { animation: arrowPulse 1.6s ease-in-out infinite; }

      `}</style>

      {/* Dot grid */}
      <div
        className="pointer-events-none fixed inset-0 z-0"
        style={{
          backgroundImage: "radial-gradient(circle, var(--muted-foreground) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
          opacity: 0.22,
        }}
      />


      {/* Cursor spotlight */}
      <div
        ref={spotRef}
        className="pointer-events-none fixed z-0 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full"
        style={{
          backgroundColor: "var(--primary)",
          opacity: 0.09,
          filter: "blur(80px)",
          transition: "left 80ms ease-out, top 80ms ease-out",
        }}
      />

      {/* Top bar */}
      <div className="relative z-10 flex items-center justify-between px-8 pt-7">
        <div />
        <span className="text-[11px] font-medium tracking-wide text-muted-foreground border border-border rounded-full px-3.5 py-1 bg-card/70">
          UC Berkeley AI Hackathon 2026
        </span>
      </div>

      {/* Hero */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 text-center relative z-10">
        <h1 className="text-[96px] font-normal tracking-[-0.04em] leading-none mb-6 text-foreground">
          AuData
        </h1>

        <p className="text-base text-muted-foreground max-w-sm mb-8 leading-relaxed">
          Catch statistical errors, numerical inconsistencies,<br />
          figure manipulation, and citation problems in biomedical papers.
        </p>

        {/* Stats row */}
        <div className="flex items-center gap-6 mb-10">
          {STATS.map(({ value, label }, i) => (
            <div key={label} className="flex items-center gap-6">
              <div className="text-center">
                <p className="text-xl font-semibold text-foreground tabular-nums">{value}</p>
                <p className="text-[10px] text-muted-foreground uppercase tracking-widest">{label}</p>
              </div>
              {i < STATS.length - 1 && <div className="h-6 w-px bg-border" />}
            </div>
          ))}
        </div>

        <Button size="lg" onClick={onEnter} className="px-10 h-12 text-[15px] gap-2">
          Start auditing <ArrowRight className="size-4 arrow-pulse" />
        </Button>

        <p className="mt-4 text-[11px] text-muted-foreground/50 tracking-wide">
          Press <kbd className="font-mono bg-muted px-1.5 py-0.5 rounded text-[10px]">Enter</kbd> to start
        </p>

        {/* Auditor list — inline below CTA */}
        <div className="mt-12 flex flex-wrap justify-center gap-x-8 gap-y-3">
          {AUDITORS.map(({ icon: Icon, label }, i) => (
            <div
              key={label}
              className="auditor-card flex items-center gap-2 cursor-default pointer-events-none transition-all duration-500"
              style={{
                animationDelay: `${i * 70}ms`,
                color: activeChip === i ? "var(--foreground)" : "var(--muted-foreground)",
              }}
            >
              <Icon className="size-3.5 shrink-0" style={{ color: activeChip === i ? "var(--primary)" : undefined }} />
              <span className="text-[11px] font-medium whitespace-nowrap">{label}</span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
