import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from database import SessionLocal
from exceptions import EarningsLensError
from models import Report, Watchlist
from schemas import ReportJSON
from services.analyst import generate_report
from services.signals.aggregator import fetch_external_context
from services.transcript import fetch_transcript

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="America/New_York")


async def _analyse_ticker(ticker: str) -> ReportJSON | None:
    try:
        transcript = await fetch_transcript(ticker)
        external = await fetch_external_context(ticker)
        report = await generate_report(transcript.text, ticker, external)

        async with SessionLocal() as db:
            db_report = Report(
                ticker=ticker,
                company=report.company,
                quarter=report.quarter,
                report_date=transcript.report_date,
                transcript_source=transcript.source,
                raw_transcript=transcript.text,
                report_json=report.model_dump(),
            )
            db.add(db_report)
            await db.commit()

        return report
    except EarningsLensError as exc:
        logger.warning("Scheduled analysis failed for %s: %s", ticker, exc)
        return None


async def _get_watched_tickers() -> list[str]:
    async with SessionLocal() as db:
        result = await db.execute(select(Watchlist))
        return [row.ticker for row in result.scalars().all()]


async def _check_earnings_day() -> None:
    """Daily 8 PM ET — analyse watched tickers with fresh earnings today."""
    today = date.today()
    tickers = await _get_watched_tickers()
    if not tickers:
        return

    for ticker in tickers:
        report = await _analyse_ticker(ticker)
        if report:
            logger.info("Earnings day report generated for %s (%s)", ticker, today)


async def _check_daily() -> None:
    """Daily 7 AM ET — analyse all watched tickers and cache results."""
    tickers = await _get_watched_tickers()
    for ticker in tickers:
        await _analyse_ticker(ticker)


async def _compile_weekly() -> None:
    """Monday 6 AM ET — re-analyse all watched tickers for weekly cache refresh."""
    tickers = await _get_watched_tickers()
    for ticker in tickers:
        await _analyse_ticker(ticker)


async def start_scheduler() -> None:
    _scheduler.add_job(_check_earnings_day, CronTrigger(hour=20, minute=0), id="earnings_day", replace_existing=True)
    _scheduler.add_job(_check_daily, CronTrigger(hour=7, minute=0), id="daily", replace_existing=True)
    _scheduler.add_job(_compile_weekly, CronTrigger(day_of_week="mon", hour=6, minute=0), id="weekly", replace_existing=True)
    _scheduler.start()
    logger.info("APScheduler started with jobs: earnings_day, daily, weekly")


async def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")
