"""FastAPI server exposing trading engine state for Next.js UI."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from engine_state import EngineState
from trading_engine import TradingEngine


def create_app(
    *,
    state: EngineState | None = None,
    engine: TradingEngine | None = None,
    start_engine_on_startup: bool = True,
) -> FastAPI:
    """Create FastAPI app for runtime and tests."""
    app = FastAPI(title="Paper Trading Live API", version="1.0.0")
    shared_state = state or EngineState()
    shared_engine = engine or TradingEngine(state=shared_state, auto_trade=True)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.engine = shared_engine
    app.state.state = shared_state
    app.state.start_engine_on_startup = start_engine_on_startup

    @app.on_event("startup")
    async def _startup():
        if app.state.start_engine_on_startup:
            app.state.engine.start()

    @app.on_event("shutdown")
    async def _shutdown():
        if app.state.start_engine_on_startup:
            app.state.engine.stop()

    @app.get("/")
    async def root():
        return {"service": "paper-trading-live-api", "docs": "/docs"}

    @app.get("/api/health")
    async def health():
        snap = app.state.state.snapshot()
        status = snap.get("status", {})
        return {
            "ok": True,
            "running": status.get("running", False),
            "feed_connected": status.get("feed_connected", False),
            "last_update_ts": status.get("last_update_ts"),
            "last_error": status.get("last_error"),
        }

    @app.get("/api/snapshot")
    async def snapshot():
        return JSONResponse(content=app.state.state.snapshot())

    @app.get("/api/history/depth")
    async def depth_history(limit: int = Query(default=200, ge=1, le=2000)):
        return {"rows": app.state.state.depth_history(limit=limit)}

    @app.get("/api/history/trades")
    async def trade_history(limit: int = Query(default=200, ge=1, le=2000)):
        return {"rows": app.state.state.trade_history(limit=limit)}

    @app.get("/api/stream")
    async def stream(request: Request):
        async def event_generator():
            while True:
                if await request.is_disconnected():
                    break
                payload = app.state.state.snapshot()
                yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(1.0)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    return app


app = create_app()
