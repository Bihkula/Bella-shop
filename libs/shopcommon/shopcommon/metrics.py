"""Prometheus RED metrics (Rate, Errors, Duration) as pure ASGI middleware."""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled",
    ["service", "method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_IN_FLIGHT = Gauge(
    "http_requests_in_flight", "Requests currently being served", ["service"]
)

_SKIP = {"/metrics", "/healthz", "/readyz"}


class PrometheusMiddleware:
    def __init__(self, app, service: str) -> None:
        self.app = app
        self.service = service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        start = time.perf_counter()
        in_flight = HTTP_IN_FLIGHT.labels(self.service)
        in_flight.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            in_flight.dec()
            route = scope.get("route")
            # Use the route template (/orders/{order_id}) not the raw path,
            # so label cardinality stays bounded.
            path = getattr(route, "path", None) or "unmatched"
            if path not in _SKIP:
                method = scope.get("method", "GET")
                HTTP_REQUESTS.labels(self.service, method, path, str(status["code"])).inc()
                HTTP_LATENCY.labels(self.service, method, path).observe(
                    time.perf_counter() - start
                )
