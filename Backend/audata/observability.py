"""Arize / Phoenix tracing for AuData (gated, no-op unless configured).

Instruments LangChain so every LLM call the detectors make is traced as a span.
Routing:
  • ARIZE_API_KEY + ARIZE_SPACE_ID set  -> Arize cloud
  • PHOENIX_COLLECTOR_ENDPOINT set (or AUDATA_PHOENIX=1) -> local Phoenix / any OTLP collector
  • otherwise                            -> disabled
"""

from __future__ import annotations

import os

_done = False


def setup() -> None:
    global _done
    if _done:
        return
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
    except Exception as e:
        print(f"[audata.obs] openinference not available ({e}); tracing off.")
        return

    try:
        if os.getenv("ARIZE_API_KEY") and os.getenv("ARIZE_SPACE_ID"):
            from arize.otel import register
            tp = register(
                space_id=os.getenv("ARIZE_SPACE_ID"),
                api_key=os.getenv("ARIZE_API_KEY"),
                project_name=os.getenv("ARIZE_PROJECT", "audata"),
            )
            LangChainInstrumentor().instrument(tracer_provider=tp)
            print("[audata.obs] Arize tracing enabled.")
            _done = True
            return

        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
        if endpoint or os.getenv("AUDATA_PHOENIX", "").lower() in ("1", "true", "yes"):
            endpoint = endpoint or "http://localhost:6006/v1/traces"
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            tp = TracerProvider(resource=Resource.create({"service.name": "audata"}))
            tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            LangChainInstrumentor().instrument(tracer_provider=tp)
            print(f"[audata.obs] Phoenix/OTLP tracing enabled -> {endpoint}")
            _done = True
            return
    except Exception as e:
        print(f"[audata.obs] tracing setup skipped: {e}")
