import logging
import os
from typing import Literal

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from exceptions import EmailError
from schemas import ReportJSON

logger = logging.getLogger(__name__)

_SIGNAL_COLORS = {"BUY": "#22c55e", "HOLD": "#f59e0b", "WATCH": "#ef4444"}


def _signal_badge(signal: str) -> str:
    color = _SIGNAL_COLORS.get(signal, "#6b7280")
    return f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:4px;font-weight:bold;font-family:monospace">{signal}</span>'


def _summary_html(report: ReportJSON, app_url: str) -> str:
    badge = _signal_badge(report.signal)
    highlights = "".join(f"<li>{h}</li>" for h in report.keyHighlights[:3])
    return f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2 style="font-family:Georgia,serif">{report.company} — {report.quarter} Earnings</h2>
  <p>Signal: {badge} &nbsp; Confidence: <strong>{report.signalConfidence:.0f}/100</strong></p>
  <p style="color:#555">{report.signalRationale}</p>
  <h3>Highlights</h3><ul>{highlights}</ul>
  <p><a href="{app_url}" style="color:#3b82f6">View full report →</a></p>
</body></html>
"""


def _full_html(report: ReportJSON, app_url: str) -> str:
    badge = _signal_badge(report.signal)
    highlights = "".join(f"<li>{h}</li>" for h in report.keyHighlights)
    watchlist = "".join(f"<li>{w}</li>" for w in report.watchlist)
    risks = "".join(
        f'<li><span style="color:{{"high":"#ef4444","med":"#f59e0b","low":"#22c55e"}.get(r.level,"#555")}">[{r.level.upper()}]</span> {r.text}</li>'
        for r in report.risks
    )
    source = report.sourceSignals
    contradictions_html = ""
    if report.contradictions:
        items = "".join(f"<li>{c}</li>" for c in report.contradictions)
        contradictions_html = f"<h3>Contradictions</h3><ul>{items}</ul>"

    return f"""
<html><body style="font-family:sans-serif;max-width:700px;margin:0 auto;padding:20px">
  <h1 style="font-family:Georgia,serif">{report.company}</h1>
  <p style="color:#888">{report.ticker} · {report.quarter} · {report.reportDate}</p>
  <hr>
  <h2>Signal: {badge} &nbsp; <span style="font-size:0.8em;color:#555">Confidence {report.signalConfidence:.0f}%</span></h2>
  <p>{report.signalRationale}</p>
  <p style="font-family:monospace;font-size:0.85em;color:#555">
    T: {source.transcript or "—"} &nbsp;|&nbsp;
    N: {source.news or "—"} &nbsp;|&nbsp;
    A: {source.analysts or "—"} &nbsp;|&nbsp;
    R: {source.reddit or "—"}
  </p>
  {contradictions_html}
  <hr>
  <h3>Executive Summary</h3><p>{report.executiveSummary}</p>
  <h3>Key Highlights</h3><ul>{highlights}</ul>
  <h3>Watch Next Quarter</h3><ul>{watchlist}</ul>
  <h3>Risks</h3><ul>{risks}</ul>
  <hr>
  <h3>Sentiment</h3>
  <p>Overall: {report.sentiment.overall:.0f} | CEO Confidence: {report.sentiment.ceoConfidence:.0f} | Forward-Looking: {report.sentiment.forwardLooking:.0f} | Caution: {report.sentiment.caution:.0f}</p>
  <p><a href="{app_url}" style="color:#3b82f6">Open in EarningsLens →</a></p>
</body></html>
"""


def _bullets_html(report: ReportJSON, app_url: str) -> str:
    badge = _signal_badge(report.signal)
    highlights = "".join(f"<li>{h}</li>" for h in report.keyHighlights)
    watchlist = "".join(f"<li>{w}</li>" for w in report.watchlist)
    contradictions_html = ""
    if report.contradictions:
        items = "".join(f'<li style="color:#ef4444">{c}</li>' for c in report.contradictions)
        contradictions_html = f"<p><strong>⚠ Contradictions:</strong></p><ul>{items}</ul>"
    return f"""
<html><body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px">
  <h2>{report.company} — {report.quarter}</h2>
  <p>Signal: {badge} ({report.signalConfidence:.0f}% confidence)</p>
  <h3>Highlights</h3><ul>{highlights}</ul>
  <h3>Watch Next Quarter</h3><ul>{watchlist}</ul>
  {contradictions_html}
  <p><a href="{app_url}" style="color:#3b82f6">Full report →</a></p>
</body></html>
"""


def _render(report: ReportJSON, fmt: str, app_url: str) -> str:
    if fmt == "full":
        return _full_html(report, app_url)
    if fmt == "bullets":
        return _bullets_html(report, app_url)
    return _summary_html(report, app_url)


async def send_report_email(
    to: str,
    report: ReportJSON,
    fmt: Literal["summary", "full", "bullets"],
    app_url: str,
) -> None:
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "reports@earningslens.app")
    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — email not sent")
        return

    subject = f"[EarningsLens] {report.ticker} {report.quarter} — {report.signal}"
    html = _render(report, fmt, app_url)

    try:
        sg = SendGridAPIClient(api_key)
        message = Mail(from_email=from_email, to_emails=to, subject=subject, html_content=html)
        sg.send(message)
        logger.info("Report email sent to %s for %s", to, report.ticker)
    except Exception as exc:
        raise EmailError(f"SendGrid failed: {exc}") from exc


async def send_digest_email(
    to: str,
    reports: list[ReportJSON],
    fmt: str,
    app_url: str,
) -> None:
    if not reports:
        return

    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL", "reports@earningslens.app")
    if not api_key:
        logger.warning("SENDGRID_API_KEY not set — digest email not sent")
        return

    tickers = ", ".join(r.ticker for r in reports)
    subject = f"[EarningsLens] Weekly Digest — {tickers}"

    sections = "".join(_render(r, fmt, app_url) for r in reports)
    html = f"<html><body>{sections}</body></html>"

    try:
        sg = SendGridAPIClient(api_key)
        message = Mail(from_email=from_email, to_emails=to, subject=subject, html_content=html)
        sg.send(message)
        logger.info("Digest email sent to %s (%d reports)", to, len(reports))
    except Exception as exc:
        raise EmailError(f"SendGrid digest failed: {exc}") from exc
