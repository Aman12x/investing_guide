"""Layer 6 — API contract tests against an ephemeral Postgres via testcontainers."""
import asyncio
import copy
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

try:
    from testcontainers.postgres import PostgresContainer
    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

pytestmark = pytest.mark.skipif(not HAS_DOCKER, reason="Docker not available")


# ── container & schema ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_url():
    """Start a Postgres container once per session; create all tables; yield asyncpg URL."""
    with PostgresContainer("postgres:15-alpine") as pg:
        raw = pg.get_connection_url()
        async_url = (
            raw
            .replace("postgresql+psycopg2://", "postgresql+asyncpg://")
            .replace("postgresql://", "postgresql+asyncpg://")
        )

        async def _setup():
            import models  # noqa: F401 — registers ORM classes on Base.metadata
            from database import Base

            engine = create_async_engine(async_url, echo=False)
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await engine.dispose()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_setup())
        finally:
            loop.close()

        yield async_url


@pytest_asyncio.fixture
async def db_session(pg_url) -> AsyncSession:
    """Return a clean DB session; truncate all tables before each test."""
    import models  # noqa: F401
    from database import Base

    engine = create_async_engine(pg_url, echo=False)
    async with engine.begin() as conn:
        for tbl in reversed(Base.metadata.sorted_tables):
            await conn.execute(tbl.delete())

    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(pg_url):
    """FastAPI AsyncClient backed by the test Postgres."""
    from database import get_db
    from main import app

    engine = create_async_engine(pg_url, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with SessionFactory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


# ── helpers ───────────────────────────────────────────────────────────────────

def _valid_report(ticker: str = "AAPL", quarter: str = "Q1 2025") -> dict:
    return {
        "company": "Apple Inc",
        "ticker": ticker,
        "quarter": quarter,
        "reportDate": "January 30, 2025",
        "signal": "HOLD",
        "signalRationale": "Steady performance with maintained guidance.",
        "signalConfidence": 65,
        "signalChanged": False,
        "sourceSignals": {"transcript": "HOLD", "news": None, "analysts": None, "reddit": None},
        "contradictions": [],
        "metrics": {
            "revenue": {"value": "$124b", "delta": "+4%", "beat": True},
            "eps": {"value": "$2.18", "delta": "+8%", "beat": True},
            "operatingMargin": {"value": "31%", "delta": "+50bps", "beat": True},
            "guidance": {"value": "$500b", "delta": "maintained", "beat": False},
        },
        "executiveSummary": "Apple delivered steady results. Services grew. Guidance maintained. No surprises.",
        "keyHighlights": ["h1", "h2", "h3", "h4", "h5"],
        "watchlist": ["w1", "w2", "w3"],
        "risks": [{"text": "China risk", "level": "high"}],
        "sentiment": {"overall": 65, "ceoConfidence": 70, "forwardLooking": 60, "caution": 35},
        "managementTone": {
            "openingTone": "confident",
            "guidanceLanguage": "maintained",
            "QATone": "measured",
            "keyTheme": "services",
        },
    }


def _agent_returning(report: dict):
    """Context-manager patch that makes agent.ainvoke return a state with final_report set."""
    from agent.state import AgentState
    from services.models import TranscriptResult
    from datetime import date

    mock_transcript = TranscriptResult(
        ticker=report["ticker"], text="operator " + "x" * 3000,
        source="fmp", quarter=report["quarter"], report_date=date(2025, 1, 30),
    )

    async def _fake_ainvoke(state):
        return AgentState(
            ticker=state.ticker,
            user_intent=state.user_intent,
            plan={},
            transcript=mock_transcript,
            signals={},
            draft_report=report,
            final_report=report,
            reflection_notes="mocked",
            iterations=1,
            sufficient=True,
        )

    return patch("routers.analyze.agent.ainvoke", _fake_ainvoke)


# ── test 1: ticker validation ─────────────────────────────────────────────────

@pytest.mark.parametrize("bad_ticker", ["aapl", "TOOLONGTICKER", "AA PL", "AA@PL"])
async def test_invalid_ticker_returns_422(client, bad_ticker):
    resp = await client.post(f"/analyze/{bad_ticker}")
    assert resp.status_code == 422


async def test_valid_ticker_not_422(client):
    with _agent_returning(_valid_report("AAPL")):
        resp = await client.post("/analyze/AAPL")
    assert resp.status_code != 422


# ── test 2: cache hit ─────────────────────────────────────────────────────────

async def test_cache_hit_returns_without_calling_claude(client, db_session):
    from models import Report

    report_data = _valid_report("MSFT", "Q1 2025")
    row = Report(
        ticker="MSFT",
        company="Microsoft",
        quarter="Q1 2025",
        report_date=None,
        transcript_source="fmp",
        raw_transcript="",
        report_json=report_data,
    )
    db_session.add(row)
    await db_session.commit()

    mock_ainvoke = AsyncMock()
    with patch("routers.analyze.agent.ainvoke", mock_ainvoke):
        resp = await client.get("/analyze/MSFT/latest")

    assert resp.status_code == 200
    mock_ainvoke.assert_not_called()
    assert resp.json()["ticker"] == "MSFT"


# ── test 3: stale cache miss triggers fresh analysis ─────────────────────────

async def test_stale_cache_not_returned_on_latest(client, db_session):
    from models import Report

    stale_report = _valid_report("GOOG", "Q4 2024")
    stale_time = datetime.utcnow() - timedelta(hours=25)
    row = Report(
        ticker="GOOG",
        company="Alphabet",
        quarter="Q4 2024",
        report_date=None,
        transcript_source="fmp",
        raw_transcript="",
        report_json=stale_report,
        created_at=stale_time,
    )
    db_session.add(row)
    await db_session.commit()

    resp = await client.get("/analyze/GOOG/latest")
    assert resp.status_code == 404  # stale → no cached report returned


# ── test 4: concurrent duplicate insert → one row ────────────────────────────

async def test_concurrent_duplicate_insert_produces_one_row(pg_url):
    """Two simultaneous /analyze calls for same ticker+quarter → only one DB row."""
    from database import get_db
    from main import app
    from models import Report
    from sqlalchemy import select

    engine = create_async_engine(pg_url, echo=False)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with SessionFactory() as s:
            yield s

    # Clean slate
    async with engine.begin() as conn:
        await conn.execute(Report.__table__.delete())

    app.dependency_overrides[get_db] = _override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            with _agent_returning(_valid_report("NVDA", "Q1 2025")):
                r1, r2 = await asyncio.gather(
                    ac.post("/analyze/NVDA"),
                    ac.post("/analyze/NVDA"),
                )
    finally:
        app.dependency_overrides.clear()

    # Both requests must succeed (200 or possibly one 502 on conflict path)
    assert r1.status_code in (200, 502)
    assert r2.status_code in (200, 502)

    # Only one row in DB
    async with engine.begin() as conn:
        result = await conn.execute(select(Report).where(Report.ticker == "NVDA"))
        rows = result.fetchall()
    await engine.dispose()

    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"


# ── test 5: error response shape ─────────────────────────────────────────────

async def test_transcript_not_found_error_returns_structured_json(client):
    from exceptions import TranscriptNotFoundError

    async def _raise(_state):
        raise TranscriptNotFoundError("FAKE")

    with patch("routers.analyze.agent.ainvoke", _raise):
        resp = await client.post("/analyze/FAKE")

    assert resp.status_code in (400, 404, 502)
    body = resp.json()
    assert "error" in body
    assert "code" in body


# ── test 6: /health always 200 ────────────────────────────────────────────────

async def test_health_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── test 7: raw_transcript never in response ──────────────────────────────────

async def test_raw_transcript_not_in_analyze_response(client):
    with _agent_returning(_valid_report("META")):
        resp = await client.post("/analyze/META")

    assert resp.status_code == 200
    assert "raw_transcript" not in resp.json()
