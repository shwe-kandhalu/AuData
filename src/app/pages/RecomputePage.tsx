import { Fragment, useEffect, useState } from "react";
import { AlertCircle, Calculator, CheckCircle2, FileInput, Play, XCircle } from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { useStore } from "../lib/store";
import { AuditStore, StatisticalAuditService, apiConfig, type StatisticalFinding, type StatisticalRecomputeResult } from "../lib/apiClient";

function fmtP(value: number) {
  if (!Number.isFinite(value)) return "n/a";
  if (value < 0.0001) return value.toExponential(2);
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function fmtInputs(inputs: Record<string, number>) {
  return Object.entries(inputs)
    .map(([key, value]) => `${key}=${fmtP(value)}`)
    .join(", ");
}

function prettyTest(name: string) {
  return name.replace(/_/g, " ");
}

function statusLabel(status: StatisticalFinding["status"]) {
  if (status === "ok") return "OK";
  if (status === "mismatch") return "Mismatch";
  return "Unknown";
}

function detailsLabel(status: StatisticalFinding["status"]) {
  return status === "ok" ? "Verification Details" : "Why this was flagged";
}

function HighlightedQuote({ quote, match }: { quote: string; match: string }) {
  const index = quote.indexOf(match);
  if (!match || index < 0) return <>{quote}</>;
  return (
    <>
      {quote.slice(0, index)}
      <mark className="rounded bg-yellow-200 px-1 text-foreground">{match}</mark>
      {quote.slice(index + match.length)}
    </>
  );
}

function ClaimText({ claim }: { claim: string }) {
  const match = claim.match(/^(.*?,\s*)(p\s*[<>=]\s*.+)$/i);
  if (!match) return <>{claim}</>;
  const pPart = match[2].replace(/\s+/g, "\u00a0");
  return (
    <>
      {match[1]}
      <span className="whitespace-nowrap">{pPart}</span>
    </>
  );
}

function pdfHref(paperId: string, finding: StatisticalFinding) {
  if (!finding.evidence.page) return undefined;
  const boxes = encodeURIComponent(JSON.stringify(finding.evidence.bboxes || []));
  const firstBox = finding.evidence.bboxes?.[0];
  const left = Math.max(0, Math.floor((firstBox?.x0 || 0) - 40));
  const top = Math.max(0, Math.floor((firstBox?.y0 || 0) - 90));
  const target = firstBox
    ? `page=${finding.evidence.page}&zoom=150,${left},${top}`
    : `page=${finding.evidence.page}`;
  return `${apiConfig.baseUrl}/audit/pdf-highlight?id=${encodeURIComponent(paperId)}&page=${finding.evidence.page}&boxes=${boxes}#${target}`;
}

export function RecomputePage() {
  const store = useStore();
  const paper = store.paperUnderAudit;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<StatisticalRecomputeResult | null>(null);
  const auditKey = paper?.id || "__none__";

  useEffect(() => {
    setResult(store.statAudits[auditKey]?.result || null);
  }, [auditKey, store.statAudits]);

  async function runAudit() {
    if (!paper) return;
    setBusy(true);
    setError("");
    try {
      const auditResult = await StatisticalAuditService.recompute(paper);
      setResult(auditResult);
      const entry = {
        result: auditResult,
        summary: { total: auditResult.claim_count, flagged: auditResult.mismatch_count },
        ranAt: Date.now(),
      };
      store.setStatAudits({ ...store.statAudits, [paper.id]: entry });
      AuditStore.save(paper.id, "statistical", entry);
    } catch (e: any) {
      setError(e?.message || "Statistical recompute failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!paper) {
    return (
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-md bg-muted p-3"><FileInput className="size-5 text-muted-foreground" /></div>
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-semibold">No paper loaded</h2>
              <p className="text-sm text-muted-foreground">Upload or fetch a paper in Ingest first.</p>
            </div>
            <Button onClick={() => store.setPage("ingest")} variant="outline">Open Ingest</Button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <div className="shrink-0 rounded-md bg-primary/10 p-3"><Calculator className="size-5 text-primary" /></div>
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold">Statistical Recompute</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Recompute reported t, F, chi-square, and r statistics against their p-values.
              </p>
            </div>
          </div>
          <Button onClick={runAudit} disabled={busy || !paper.full_text} className="shrink-0 gap-2 md:self-start">
            <Play className="size-4" />
            {busy ? "Running" : "Run check"}
          </Button>
        </div>
      </Card>

      {error && (
        <Card className="p-4 border-destructive/40">
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="size-4" />
            {error}
          </div>
        </Card>
      )}

      {result && (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Claims</div>
              <div className="text-2xl font-semibold">{result.claim_count}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Mismatches</div>
              <div className="text-2xl font-semibold">{result.mismatch_count}</div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Supported Tests</div>
              <div className="text-sm font-medium">t, F, chi-square, r</div>
            </Card>
          </div>

          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/60 text-left">
                  <tr>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">Claim</th>
                    <th className="px-4 py-3 font-medium">Source Quote</th>
                    <th className="whitespace-nowrap px-4 py-3 text-right font-medium">Computed p</th>
                    <th className="px-4 py-3 font-medium">Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {result.findings.map((finding, index) => {
                    const href = pdfHref(paper.id, finding);
                    return (
                    <Fragment key={`${finding.claim}-${index}`}>
                      <tr className="border-t">
                        <td className="px-4 py-3">
                          <Badge
                            variant="outline"
                            className={finding.status === "mismatch"
                              ? "border-destructive/40 text-destructive"
                              : "border-emerald-500/30 text-emerald-600"}
                          >
                            {finding.status === "mismatch"
                              ? <XCircle className="mr-1 size-3" />
                              : <CheckCircle2 className="mr-1 size-3" />}
                            {statusLabel(finding.status)}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          <code className="text-xs">
                            <ClaimText claim={finding.claim} />
                          </code>
                        </td>
                        <td className="px-4 py-3 max-w-md">
                          {href ? (
                            <a className="block text-primary hover:underline" href={href} target="_blank" rel="noreferrer">
                              <span
                                className="block overflow-hidden"
                                style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2 }}
                              >
                                {finding.evidence.quote}
                              </span>
                            </a>
                          ) : (
                            <span
                              className="block overflow-hidden"
                              style={{ display: "-webkit-box", WebkitBoxOrient: "vertical", WebkitLineClamp: 2 }}
                            >
                              {finding.evidence.quote}
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-right">{fmtP(finding.recomputed_p)}</td>
                        <td className="px-4 py-3 text-muted-foreground">{finding.note}</td>
                      </tr>
                      <tr className="border-t bg-muted/20">
                        <td colSpan={5} className="px-4 py-3">
                          <details className="rounded-md border bg-background p-3">
                            <summary className="cursor-pointer text-sm font-medium">{detailsLabel(finding.status)}</summary>
                            <div className="mt-3 grid gap-4 md:grid-cols-2">
                              <div className="space-y-2">
                                <div className="text-xs font-medium text-muted-foreground">Source quote</div>
                                <blockquote className="text-sm border-l pl-3 text-muted-foreground">
                                  <HighlightedQuote quote={finding.evidence.quote} match={finding.evidence.exact_quote} />
                                </blockquote>
                              </div>
                              <div className="space-y-3">
                                <div className="text-xs font-medium text-muted-foreground">
                                  {finding.status === "ok" ? "Verification Details" : "Math breakdown"}
                                </div>
                                <ol className="space-y-3 text-sm">
                                  <li>
                                    <div className="font-medium">1. Test type</div>
                                    <div className="text-muted-foreground">{prettyTest(finding.math.test)}</div>
                                  </li>
                                  <li>
                                    <div className="font-medium">2. Extract the reported values</div>
                                    <code className="block text-xs bg-muted p-2 rounded">{fmtInputs(finding.math.inputs)}</code>
                                  </li>
                                  <li>
                                    <div className="font-medium">3. Use the p-value formula</div>
                                    <code className="block text-xs bg-muted p-2 rounded">{finding.math.formula}</code>
                                  </li>
                                  <li>
                                    <div className="font-medium">4. Substitute the extracted values</div>
                                    <code className="block text-xs bg-muted p-2 rounded">{finding.math.substitution}</code>
                                  </li>
                                  <li>
                                    <div className="font-medium">5. Recompute and compare</div>
                                    <div>
                                      Reported <code>{finding.reported_p}</code>; recomputed <code>p={fmtP(finding.math.result)}</code>.
                                    </div>
                                    {finding.status === "mismatch" && (
                                      <div className="mt-1">
                                        Difference <code>{fmtP(finding.difference)}</code>.
                                      </div>
                                    )}
                                  </li>
                                  <li>
                                    <div className="font-medium">6. Verdict</div>
                                    <div className={finding.status === "mismatch" ? "text-destructive" : "text-emerald-600"}>
                                      {statusLabel(finding.status)}: {finding.note}
                                    </div>
                                    <div className="mt-1 text-muted-foreground">Confidence: {finding.confidence}</div>
                                  </li>
                                </ol>
                              </div>
                            </div>
                          </details>
                        </td>
                      </tr>
                    </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {result.findings.length === 0 && (
            <Card className="p-8 text-center">
              <div className="font-medium">No supported statistical claims were found.</div>
              <p className="mx-auto mt-2 max-w-2xl text-sm text-muted-foreground">
                {result.no_findings_reason || "The extracted text did not contain a supported t, F, chi-square, or r claim paired with a p-value."}
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
