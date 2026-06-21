// Renders a PDF with pdf.js, fit to the container width, and highlights the
// full sentence(s) containing any of the given terms (expanded from the matched
// text run to sentence boundaries). Scrolls to the first match. Used to
// evidence-link a flagged reference to where it appears in the paper.

import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { Loader2 } from "lucide-react";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

// Safari doesn't implement async iteration on ReadableStream, which pdf.js uses
// internally (getTextContent) → "undefined is not a function (...readableStream)".
(() => {
  const proto: any = typeof ReadableStream !== "undefined" ? ReadableStream.prototype : null;
  if (proto && !proto[Symbol.asyncIterator]) {
    proto[Symbol.asyncIterator] = function () {
      const reader = this.getReader();
      return {
        next() { return reader.read(); },
        return() { try { reader.releaseLock(); } catch { /* noop */ } return Promise.resolve({ done: true, value: undefined }); },
        [Symbol.asyncIterator]() { return this; },
      };
    };
    if (!proto.values) proto.values = function () { return this[Symbol.asyncIterator](); };
  }
})();

export function PdfHighlightViewer({ url, terms }: { url: string; terms: string[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [err, setErr] = useState("");
  const [matchCount, setMatchCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = "";
    setStatus("loading"); setErr(""); setMatchCount(0);
    const lowTerms = terms.map((t) => (t || "").toLowerCase().trim()).filter((t) => t.length >= 3);

    (async () => {
      let matches = 0;
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`Could not load PDF (${resp.status})`);
        const data = new Uint8Array(await resp.arrayBuffer());
        if (cancelled) return;
        const pdf = await pdfjsLib.getDocument({ data }).promise;
        if (cancelled) return;

        // Fit the page width to the container. Wait a frame so the dialog has
        // finished laying out before measuring (otherwise width reads as 0).
        const first = await pdf.getPage(1);
        const base = first.getViewport({ scale: 1 });
        await new Promise<void>((r) => requestAnimationFrame(() => r()));
        if (cancelled) return;
        let cw = container.clientWidth;
        if (!cw || cw < 400) cw = Math.min(window.innerWidth * 0.92, 1320);
        const scale = Math.max(1.0, Math.min(3.5, (cw - 8) / base.width));
        // Render at device pixel ratio so text is crisp on retina displays.
        const dpr = Math.min(window.devicePixelRatio || 1, 2);

        let firstHl: HTMLElement | null = null;
        for (let n = 1; n <= pdf.numPages; n++) {
          const page = n === 1 ? first : await pdf.getPage(n);
          if (cancelled) return;
          const viewport = page.getViewport({ scale });
          const pageDiv = document.createElement("div");
          pageDiv.style.cssText = `position:relative;margin:0 auto 14px;width:${viewport.width}px;height:${viewport.height}px;box-shadow:0 1px 6px rgba(0,0,0,.18)`;
          const canvas = document.createElement("canvas");
          canvas.width = Math.floor(viewport.width * dpr);
          canvas.height = Math.floor(viewport.height * dpr);
          canvas.style.width = `${viewport.width}px`;
          canvas.style.height = `${viewport.height}px`;
          canvas.style.display = "block";
          pageDiv.appendChild(canvas);
          container.appendChild(pageDiv);
          await page.render({
            canvas, canvasContext: canvas.getContext("2d")!, viewport,
            transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
          }).promise;
          if (cancelled) return;

          if (!lowTerms.length) continue;
          try {
            const tc = await page.getTextContent();
            const items = tc.items as any[];
            // Concatenate the page text, tracking each run's char span.
            let full = "";
            const spans: { start: number; end: number; it: any }[] = [];
            for (const it of items) {
              const str = it.str || "";
              const start = full.length;
              full += str;
              spans.push({ start, end: full.length, it });
              full += it.hasEOL ? "\n" : (str && !/\s$/.test(str) ? " " : "");
            }
            const low = full.toLowerCase();
            // Expand each match to its sentence and collect unique ranges.
            const ranges = new Map<string, [number, number]>();
            for (const term of lowTerms) {
              let i = low.indexOf(term);
              while (i !== -1) {
                let s = i;
                while (s > 0 && !".!?".includes(full[s - 1])) s--;
                while (s < i && /\s/.test(full[s])) s++;
                let e = i + term.length;
                while (e < full.length && !".!?".includes(full[e])) e++;
                if (e < full.length) e++;
                ranges.set(`${s}:${e}`, [s, e]);
                i = low.indexOf(term, i + term.length);
              }
            }
            if (ranges.size) {
              const hlIdx = new Set<number>();
              for (const [rs, re] of ranges.values()) {
                spans.forEach((sp, idx) => { if (sp.start < re && sp.end > rs) hlIdx.add(idx); });
              }
              for (const idx of hlIdx) {
                const it = spans[idx].it;
                const m = pdfjsLib.Util.transform(viewport.transform, it.transform);
                const fontH = Math.hypot(m[2], m[3]) || 10;
                const w = (it.width || 0) * scale || it.str.length * fontH * 0.5;
                const hl = document.createElement("div");
                hl.style.cssText = `position:absolute;left:${m[4]}px;top:${m[5] - fontH}px;width:${w}px;height:${fontH * 1.25}px;background:rgba(250,204,21,.45);border-radius:2px;pointer-events:none`;
                pageDiv.appendChild(hl);
                if (!firstHl) firstHl = hl;
              }
              matches += ranges.size;
            }
          } catch { /* text extraction failed on this page — keep rendering */ }
        }
        if (cancelled) return;
        setMatchCount(matches);
        setStatus("ready");
        if (firstHl) setTimeout(() => firstHl!.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
      } catch (e: any) {
        if (!cancelled) { setErr(e?.message || "Failed to render PDF"); setStatus("error"); }
      }
    })();
    return () => { cancelled = true; };
  }, [url, terms.join("|")]);

  return (
    <div className="space-y-2">
      {status === "loading" && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Rendering PDF…</div>}
      {status === "error" && <div className="text-sm text-red-600">Couldn't render PDF: {err}</div>}
      {status === "ready" && (
        <div className="text-xs text-muted-foreground">
          {matchCount > 0 ? `Highlighted ${matchCount} passage${matchCount === 1 ? "" : "s"} — scrolled to the first.` : "No matching text found to highlight in the PDF."}
        </div>
      )}
      <div ref={containerRef} className="overflow-auto max-h-[85vh] bg-muted/30 rounded p-1" />
    </div>
  );
}
