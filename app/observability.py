"""Optional Langfuse spans. No customer text or contact data is sent by default."""
from __future__ import annotations

import logging
from contextlib import contextmanager, nullcontext

log = logging.getLogger("resolveai.observability")
_warned: set[str] = set()


def _warn_once(key: str, message: str, *args) -> None:
    """Lỗi Langfuse ghi ở mức WARNING một lần (log Render mặc định ẩn mức INFO) nhưng không bao giờ làm gián đoạn chat."""
    if key not in _warned:
        _warned.add(key)
        log.warning(message, *args)


def status(settings) -> str:
    """Mô tả ngắn trạng thái Langfuse để ghi log khi khởi động: thiếu khóa, thiếu thư viện, sai khóa/vùng, hay đang chạy."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return "TẮT: chưa đặt LANGFUSE_PUBLIC_KEY và LANGFUSE_SECRET_KEY."
    try:
        from langfuse import Langfuse
    except Exception as exc:  # noqa: BLE001
        return f"LỖI: chưa cài thư viện langfuse ({type(exc).__name__}). Kiểm tra requirements.txt và build của Render."
    try:
        client = Langfuse(public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key,
                          host=settings.langfuse_host)
        ok = client.auth_check()
    except Exception as exc:  # noqa: BLE001
        return f"LỖI: không kết nối được tới {settings.langfuse_host} ({type(exc).__name__})."
    if ok:
        return f"BẬT: xác thực thành công với {settings.langfuse_host}."
    return (f"LỖI: Langfuse từ chối khóa tại {settings.langfuse_host}. Kiểm tra khóa có đúng project không và "
            "LANGFUSE_HOST có đúng vùng không (EU: https://cloud.langfuse.com, US: https://us.cloud.langfuse.com).")


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
        _warn_once("client", "Langfuse không khởi tạo được, tracing bị bỏ qua: %s", type(exc).__name__)
        yield None
        return
    try:
        observation = client.start_as_current_observation(name=name, as_type="span", input=metadata or {})
        current = observation.__enter__()
    except Exception as exc:
        _warn_once("start", "Langfuse không mở được span, tracing bị bỏ qua: %s", type(exc).__name__)
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
            _warn_once("flush", "Langfuse không gửi được trace (flush): %s", type(exc).__name__)
