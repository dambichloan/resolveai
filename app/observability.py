"""Optional Langfuse spans. No customer text or contact data is sent by default."""
from __future__ import annotations

import logging
from contextlib import contextmanager, nullcontext

log = logging.getLogger("resolveai.observability")


@contextmanager
def span(settings, name: str, metadata: dict | None = None):
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        with nullcontext() as current:
            yield current
        return
    try:
        from langfuse import Langfuse
        client = Langfuse(public_key=settings.langfuse_public_key,
                          secret_key=settings.langfuse_secret_key,
                          host=settings.langfuse_host)
    except Exception as exc:  # tracing outage must never interrupt customer support
        log.info("Langfuse span unavailable: %s", type(exc).__name__)
        yield None
        return
    try:
        observation = client.start_as_current_observation(name=name, as_type="span", input=metadata or {})
        current = observation.__enter__()
    except Exception as exc:
        log.info("Langfuse observation unavailable: %s", type(exc).__name__)
        yield None
        return
    error = None
    try:
        yield current
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            observation.__exit__(type(error) if error else None, error, error.__traceback__ if error else None)
        except Exception as exc:
            log.info("Langfuse observation close unavailable: %s", type(exc).__name__)
        try:
            client.flush()
        except Exception as exc:
            log.info("Langfuse flush unavailable: %s", type(exc).__name__)
