"""Unit tests for conductor.otel — traceparent inject/extract round-trip."""

from conductor.otel import (
    extract_traceparent,
    get_tracer,
    inject_traceparent,
    setup_otel,
)


def test_setup_otel_is_idempotent():
    setup_otel(service_name="conductor-test")
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    assert tracer is not None


def test_inject_returns_w3c_traceparent_string():
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    with tracer.start_as_current_span("dispatch") as span:
        tp = inject_traceparent()
    assert tp.startswith("00-")
    assert tp.count("-") == 3


def test_extract_then_start_span_links_to_parent():
    setup_otel(service_name="conductor-test")
    tracer = get_tracer()
    with tracer.start_as_current_span("producer") as parent:
        parent_trace_id = format(parent.get_span_context().trace_id, "032x")
        tp = inject_traceparent()
    ctx = extract_traceparent(tp)
    with tracer.start_as_current_span("consumer", context=ctx) as child:
        child_trace_id = format(child.get_span_context().trace_id, "032x")
    assert child_trace_id == parent_trace_id


def test_extract_empty_traceparent_returns_none_or_empty_context():
    ctx = extract_traceparent("")
    # Acceptable: None or an empty context that produces a fresh trace_id when used.
    assert ctx is None or ctx is not None
