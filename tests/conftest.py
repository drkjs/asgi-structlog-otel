import pytest 
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, Tracer
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

@pytest.fixture
def tracer_provider():
    """Fixture that provides a configured TracerProvider with in-memory export. Without it, tests would default to the NoOpTracer
       which doesn't lend itself well to testing the extraction logic.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    
    yield provider
    
    trace.set_tracer_provider(None)

@pytest.fixture
def tracer(tracer_provider) -> Tracer:
    """
    Actually provide a fully setup tracer.
    """
    return trace.get_tracer(__name__)

@pytest.fixture(autouse=True)
def clear_structlog_context():
    """
    Clear structlog context before and after each test to prevent leakage.
    """
    import structlog

    # Clear before test
    structlog.contextvars.clear_contextvars()

    yield

    # Clear after test
    structlog.contextvars.clear_contextvars()