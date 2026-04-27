"""OpenTelemetry SDK wiring (no-op exporter for Phase 0).

Producer (dispatcher) creates a span and injects W3C traceparent into the stream
message; consumer (worker) extracts it and starts a child span. No traces are
exported until Phase 4 wires up an exporter.
"""

from __future__ import annotations

import threading
from typing import Optional

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider

_lock = threading.Lock()
_initialized = False
_TRACER_NAME = "conductor"


def setup_otel(*, service_name: str = "conductor") -> None:
    """Initialize a TracerProvider once per process. No exporter (Phase 4 adds one)."""
    global _initialized
    with _lock:
        if _initialized:
            return
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
        trace.set_tracer_provider(provider)
        _initialized = True


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def inject_traceparent() -> str:
    """Return the W3C traceparent string for the current span context (or empty)."""
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get("traceparent", "")


def extract_traceparent(traceparent: str) -> Optional[otel_context.Context]:
    """Return an OTel Context to use as `context=...` when starting the consumer span."""
    if not traceparent:
        return None
    return extract({"traceparent": traceparent})
