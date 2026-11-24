"""Đo nhanh độ trễ HTTP/p95 với số request và độ đồng thời cấu hình được.

Mặc định chỉ gọi healthz để không tạo hội thoại hoặc chi phí Gemini. Khi nghiệm
thu luồng chat, truyền ``--path`` là một endpoint test được cấp riêng.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request


def call(url: str, timeout: float) -> dict:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - URL do người vận hành truyền
            response.read()
            status = response.status
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "ms": round((time.perf_counter() - started) * 1000), "error": type(exc).__name__}
    return {"ok": 200 <= status < 400, "ms": round((time.perf_counter() - started) * 1000), "status": status}


def percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int((len(values) - 1) * p)))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--path", default="/healthz")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    count, workers = max(1, args.requests), max(1, args.concurrency)
    url = args.base_url.rstrip("/") + "/" + args.path.lstrip("/")
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: call(url, args.timeout), range(count)))
    elapsed = time.perf_counter() - started
    values = [r["ms"] for r in results]
    failures = [r for r in results if not r["ok"]]
    print(json.dumps({"url": url, "requests": count, "concurrency": workers,
                      "success": count - len(failures), "failed": len(failures),
                      "p50_ms": percentile(values, 0.50), "p95_ms": percentile(values, 0.95),
                      "mean_ms": round(statistics.mean(values), 1), "throughput_rps": round(count / elapsed, 2),
                      "errors": failures[:5]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
