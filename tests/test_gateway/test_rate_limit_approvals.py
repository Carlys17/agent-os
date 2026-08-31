from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from agentos.gateway.config import GatewayConfig, RateLimitConfig
from agentos.gateway.middleware import DEFAULT_PATH_BUCKETS, RateLimitMiddleware


def _build_app(*, global_max: int, approvals_max: int | None = None) -> Starlette:
    """Stand up a tiny Starlette app with separate /api/approvals + /api/sessions handlers."""
    app = Starlette()

    async def approvals(_request):
        return JSONResponse({"approvals": []})

    async def sessions(_request):
        return JSONResponse({"ok": True})

    app.add_route("/api/approvals", approvals, methods=["GET"])
    app.add_route("/api/sessions", sessions, methods=["GET"])
    config = GatewayConfig()
    config.rate_limit.enabled = True
    config.rate_limit.max_requests = global_max
    config.rate_limit.window_seconds = 60
    if approvals_max is not None:
        # Explicit per-path override wins over the built-in default bucket.
        config.rate_limit.path_buckets = {
            "/api/approvals": RateLimitConfig(
                max_requests=approvals_max,
                window_seconds=60,
            ),
        }
    app.add_middleware(RateLimitMiddleware, config=config)
    return app


def test_approvals_uses_dedicated_bucket() -> None:
    """Two tabs worth of polling (~2x POLL_MS=1500ms cadence) must not 429."""
    # Two tabs polling at 1500 ms = 40+40 = 80 req/min; global cap is tight (2)
    # so the dedicated bucket is what keeps the poll alive.
    app = _build_app(global_max=2, approvals_max=100)

    with TestClient(app) as client:
        # /api/approvals: enough headroom for two tabs + a couple of extras.
        for _ in range(100):
            assert client.get("/api/approvals").status_code == 200
        # The 101st request hits the per-bucket cap (max_requests=100).
        assert client.get("/api/approvals").status_code == 429
        # /api/sessions: untouched by approvals traffic — its OWN bucket is
        # the global one with max_requests=2, so the very third hit trips it.
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 429


def test_approvals_bucket_does_not_drain_global_bucket() -> None:
    """Heavy approvals traffic must not poison /api/* siblings."""
    app = _build_app(global_max=1, approvals_max=500)

    with TestClient(app) as client:
        # Hammer the approvals bucket — global bucket should remain untouched.
        for _ in range(50):
            assert client.get("/api/approvals").status_code == 200
        # /api/sessions: first request uses the only slot in the global bucket.
        assert client.get("/api/sessions").status_code == 200
        # Second request — global bucket exhausted by the prior /api/sessions call.
        assert client.get("/api/sessions").status_code == 429


def test_approvals_subpath_uses_dedicated_bucket() -> None:
    """/api/approvals/* resolves under the dedicated bucket too (per-prefix match)."""
    app = Starlette()

    async def resolve(_request):
        return JSONResponse({"ok": True})

    async def sessions(_request):
        return JSONResponse({"ok": True})

    app.add_route("/api/approvals/resolve", resolve, methods=["POST"])
    app.add_route("/api/sessions", sessions, methods=["GET"])
    config = GatewayConfig()
    config.rate_limit.enabled = True
    config.rate_limit.max_requests = 1
    config.rate_limit.window_seconds = 60
    config.rate_limit.path_buckets = {
        "/api/approvals": RateLimitConfig(
            max_requests=10,
            window_seconds=60,
        ),
    }
    app.add_middleware(RateLimitMiddleware, config=config)

    with TestClient(app) as client:
        # /api/approvals/resolve is under the /api/approvals prefix -> dedicated
        # bucket. Even at 10/60s, plenty of headroom for a couple of POSTs.
        assert client.post("/api/approvals/resolve").status_code == 200
        assert client.post("/api/approvals/resolve").status_code == 200
        # /api/sessions shares the global bucket — exhausted after first hit.
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 429


def test_default_bucket_covers_approval_polling() -> None:
    """The built-in default bucket alone keeps two polling tabs under the cap."""
    # No explicit path_buckets — the middleware's DEFAULT_PATH_BUCKETS applies.
    app = _build_app(global_max=100)  # 100 req/60s shared bucket

    with TestClient(app) as client:
        # 2 tabs × 40 req/min = 80 req in a minute — all under the cap.
        for _ in range(80):
            assert client.get("/api/approvals").status_code == 200
        # Global bucket untouched by that: a fresh /api/sessions request passes.
        assert client.get("/api/sessions").status_code == 200


def test_default_path_buckets_constant() -> None:
    """The shipped default for /api/approvals is sized for ~2+ polling tabs."""
    assert "/api/approvals" in DEFAULT_PATH_BUCKETS
    assert DEFAULT_PATH_BUCKETS["/api/approvals"]["max_requests"] == 300
    assert DEFAULT_PATH_BUCKETS["/api/approvals"]["window_seconds"] == 60


def test_global_bucket_still_guards_other_api_paths() -> None:
    """Non-approvals /api/* paths are NOT exempt — they share the global bucket."""
    app = _build_app(global_max=3)

    with TestClient(app) as client:
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 200
        assert client.get("/api/sessions").status_code == 429
