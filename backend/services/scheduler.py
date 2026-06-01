import logging
import os
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from database import SessionLocal
from exceptions import EarningsLensError
from models import Report, Subscription, Watchlist
from schemas import ReportJSON
from services.analyst import generate_report
from services.email import send_digest_email, send_report_email
from services.signals.aggregator import fetch_external_context
from services.transcript import fetch_transcript

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="America/New_York")
_APP_URL = os.getenv("APP_URL", "http://localhost:3000")


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


async def _get_active_subscriptions():
    async with SessionLocal() as db:
        result = await db.execute(select(Subscription).where(Subscription.active == True))
        return result.scalars().all()


async def _get_watched_tickers() -> list[str]:
    async with SessionLocal() as db:
        result = await db.execute(select(Watchlist))
        return [row.ticker for row in result.scalars().all()]


async def _check_earnings_day() -> None:
    """Daily 8 PM ET — analyse watched tickers; email subscribers whose ticker had earnings today."""
    today = date.today()
    tickers = await _get_watched_tickers()
    if not tickers:
        return

    reports: dict[str, ReportJSON] = {}
    for ticker in tickers:
        report = await _analyse_ticker(ticker)
        if report:
            reports[ticker] = report

    subscriptions = await _get_active_subscriptions()
    for sub in subscriptions:
        to_send = []
        for ticker in (sub.tickers or []):
            r = reports.get(ticker.upper())
            if r:
                # Only send if report_date matches today (fresh earnings)
                async with SessionLocal() as db:
                    stmt = (
                        select(Report)
                        .where(Report.ticker == ticker.upper())
                        .order_by(Report.created_at.desc())
                    )
                    result = await db.execute(stmt)
                    db_report = result.scalar_one_or_none()
                    if db_report and db_report.report_date == today:
                        to_send.append(r)

        for r in to_send:
            try:
                await send_report_email(sub.email, r, sub.format or "summary", _APP_URL)
            except EarningsLensError as exc:
                logger.error("Email send failed for %s: %s", sub.email, exc)


async def _check_daily() -> None:
    """Daily 7 AM ET — analyse watched tickers; email subscribers if a new transcript was found."""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    tickers = await _get_watched_tickers()
    if not tickers:
        return

    new_reports: dict[str, ReportJSON] = {}
    for ticker in tickers:
        report = await _analyse_ticker(ticker)
        if report:
            new_reports[ticker] = report

    subscriptions = await _get_active_subscriptions()
    for sub in subscriptions:
        to_send = [
            new_reports[t.upper()]
            for t in (sub.tickers or [])
            if t.upper() in new_reports
        ]
        if not to_send:
            continue
        for r in to_send:
            try:
                await send_report_email(sub.email, r, sub.format or "summary", _APP_URL)
            except EarningsLensError as exc:
                logger.error("Daily email send failed for %s: %s", sub.email, exc)


async def _send_weekly_digest() -> None:
    """Monday 6 AM ET — compile and send digest for weekly subscribers."""
    subscriptions = await _get_active_subscriptions()
    weekly_subs = [s for s in subscriptions if s.schedule == "weekly"]
    if not weekly_subs:
        return

    # Collect latest reports for all relevant tickers
    all_tickers = {t.upper() for s in weekly_subs for t in (s.tickers or [])}
    reports: dict[str, ReportJSON] = {}

    async with SessionLocal() as db:
        for ticker in all_tickers:
            stmt = select(Report).where(Report.ticker == ticker).order_by(Report.created_at.desc())
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                try:
                    reports[ticker] = ReportJSON(**row.report_json)
                except Exception as exc:
                    logger.warning("Could not parse cached report for %s: %s", ticker, exc)

    for sub in weekly_subs:
        digest = [reports[t.upper()] for t in (sub.tickers or []) if t.upper() in reports]
        if not digest:
            continue
        try:
            await send_digest_email(sub.email, digest, sub.format or "bullets", _APP_URL)
        except EarningsLensError as exc:
            logger.error("Weekly digest failed for %s: %s", sub.email, exc)


async def start_scheduler() -> None:
    _scheduler.add_job(_check_earnings_day, CronTrigger(hour=20, minute=0), id="earnings_day", replace_existing=True)
    _scheduler.add_job(_check_daily, CronTrigger(hour=7, minute=0), id="daily", replace_existing=True)
    _scheduler.add_job(_send_weekly_digest, CronTrigger(day_of_week="mon", hour=6, minute=0), id="weekly", replace_existing=True)
    _scheduler.start()
    logger.info("APScheduler started with jobs: earnings_day, daily, weekly")


async def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("APScheduler stopped")
