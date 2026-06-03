# EarningsLens — CLAUDE.md

> Agentic earnings call analyst. Scrapes transcripts, extracts financials, scores sentiment,
> generates analyst-grade reports weighted against Reddit/news/analyst signals, and answers
> follow-up questions. Stateless open app — any user can analyze any ticker, no accounts.
> FastAPI backend · Vite/React frontend · PostgreSQL · Railway.

---

## Project map

```
earningslens/
├── CLAUDE.md
├── docker-compose.yml
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── main.py                   # FastAPI app, CORS
│   ├── database.py               # SQLAlchemy engine + session
│   ├── models.py                 # ORM: Report, Watchlist, QASession
│   ├── schemas.py                # Pydantic schemas / ReportJSON validation
│   ├── exceptions.py             # Typed exceptions: TranscriptNotFoundError, ClaudeError, etc.
│   ├── routers/
│   │   ├── analyze.py            # POST /analyze/{ticker} (SSE), GET /history, GET /latest
│   │   ├── ask.py                # POST /ask/{ticker}
│   │   ├── search.py             # GET /search?q= — FMP ticker autocomplete, 1h in-memory cache
│   │   └── watchlist.py          # GET/POST/DELETE /watchlist
│   ├── agent/
│   │   ├── state.py              # AgentState dataclass — shared across all nodes
│   │   ├── graph.py              # LangGraph StateGraph wiring; exports agent = build_graph()
│   │   └── nodes/
│   │       ├── planner.py        # Claude call — tool priorities, weight overrides
│   │       ├── tools.py          # fetch_node: wraps all services with 5s timeouts
│   │       ├── sufficiency.py    # Pure logic — routes "proceed" or "fetch_more"
│   │       ├── analyst.py        # Claude call — draft ReportJSON from transcript + signals
│   │       ├── reflector.py      # Claude call — skeptical review, produces final_report
│   │       └── formatter.py      # Pure Python — validates against ReportJSON schema
│   ├── services/
│   │   ├── transcript.py         # Waterfall: EDGAR → FMP → scraper
│   │   ├── models.py             # TranscriptResult dataclass (shared to avoid circular imports)
│   │   ├── edgar.py              # SEC EDGAR 8-K fetcher (works for companies that file transcripts)
│   │   ├── fmp_transcript.py     # Financial Modeling Prep API — primary fallback
│   │   ├── scraper.py            # Last-resort scraper fallback
│   │   ├── signals/
│   │   │   ├── __init__.py
│   │   │   ├── reddit.py         # Reddit OAuth → sentiment summary
│   │   │   ├── news.py           # NewsAPI / RSS → headline signals
│   │   │   ├── analysts.py       # Finnhub consensus ratings
│   │   │   └── aggregator.py     # asyncio.gather all three, return ExternalContext
│   │   ├── analyst.py            # Claude API — composite report generation
│   │   └── qa.py                 # Claude API — multi-turn Q&A
│   └── alembic/
│       ├── env.py
│       └── versions/
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api.js                # All fetch calls — single source of truth
        ├── components/
        │   ├── Sidebar.jsx         # Ticker combobox with FMP autocomplete dropdown
        │   ├── ReportView.jsx
        │   ├── MetricsGrid.jsx
        │   ├── SignalBlock.jsx      # Signal badge + confidence + source breakdown
        │   ├── SentimentBars.jsx
        │   ├── RiskList.jsx
        │   ├── ManagementTone.jsx
        │   ├── TrendPanel.jsx       # Multi-quarter sparklines; self-fetches /history; hidden when < 2 quarters
        │   ├── QABar.jsx
        │   └── Toast.jsx
        ├── hooks/
        │   ├── useAnalysis.js
        │   └── useQA.js
        └── pages/
            └── Home.jsx
```

---

## Local development

**Prerequisites:** Docker Desktop running.

```bash
# 1. Start Postgres + backend (from repo root)
docker compose up --build -d

# 2. Run migrations (first time only, or after schema changes)
docker compose exec backend alembic upgrade head

# 3. Start frontend (separate terminal)
cd frontend && npm run dev
```

- Backend: `http://localhost:8001` (port 8000 is taken by Docker Desktop on Mac)
- Frontend: `http://localhost:5173`
- Health check: `curl http://localhost:8001/health`

**Logs:** `docker compose logs -f backend`

**Rebuild after backend code changes:** `docker compose up --build -d backend`
The frontend hot-reloads automatically via Vite — no restart needed.

**First run:** Migrations must be applied manually after `docker compose up`. Alembic does not
run automatically in the local compose setup (only in the Railway deploy command).

---

## Environment variables

```bash
# backend/.env  ← lives here, never committed, no .env.example (permanently gitignored)
DATABASE_URL=postgresql://user:pass@localhost:5432/earningslens
ANTHROPIC_API_KEY=sk-ant-...
EDGAR_USER_AGENT="EarningsLens yourname@email.com"   # required by SEC fair-use policy
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,https://yourapp.up.railway.app

# Transcript sources (waterfall: EDGAR → FMP → Alpha Vantage)
FMP_KEY=...          # financialmodelingprep.com — free tier 250 req/day; covers all S&P 500+
                     # optional but required for major tickers (AAPL, MSFT, etc.) that don't
                     # file transcripts with EDGAR
ALPHA_VANTAGE_KEY=...  # alphavantage.co — third-tier fallback; EARNINGS_CALL_TRANSCRIPT endpoint
                       # optional; free tier limited, premium recommended for this endpoint

# External signal sources
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
NEWSAPI_KEY=...                                        # newsapi.org free tier = 100 req/day
FINNHUB_KEY=...                                        # free tier = 60 req/min

# Observability (optional — backend is fully functional without these)
LANGFUSE_PUBLIC_KEY=pk-lf-...                          # langfuse.com free tier
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com               # default; omit for cloud, set for self-hosted

# frontend/.env
VITE_API_URL=http://localhost:8001   # 8000 is used by Docker Desktop on Mac; use 8001 locally
```

**Rules:**
- Every secret is an env var. No hardcoded URLs, keys, or credentials anywhere in code.
- Never create `.env.example` — it is permanently blocked in `.gitignore`. Document variables here instead.
- Railway auto-injects `DATABASE_URL` — `database.py` must rewrite `postgres://` → `postgresql://`.
- `EDGAR_USER_AGENT` is not optional. SEC will block requests without it.
- `FMP_KEY` is optional — if absent, FMP source is skipped. EDGAR still runs first.
- All signal source keys (Reddit, NewsAPI, Finnhub) are optional — if absent, that source is
  skipped gracefully and confidence is recalculated across remaining sources.
- Langfuse keys are optional — if absent, `observability.setup()` is a no-op and all
  `@observe()` decorators on nodes/services are no-ops. Never guard Claude calls on Langfuse.

---

## Core data contracts

### AgentState (LangGraph)

```python
@dataclass
class AgentState:
    ticker: str
    user_intent: str                        # raw request from user
    plan: dict                              # planner output — tool priorities, weight overrides
    transcript: Any                         # TranscriptResult | None
    signals: dict                           # {reddit, news, analysts, market} — any can be None
    draft_report: dict                      # first ReportJSON attempt (analyst node)
    final_report: dict                      # after reflector review; validated by formatter
    reflection_notes: str                   # what the reflector changed and why
    iterations: int = 0                     # sufficiency check loop counter
    sufficient: bool = False                # did we get enough data to generate?
    errors: list[str] = field(default_factory=list)
    formatter_attempts: int = 0             # tracks formatter retry; max 1 retry allowed
```

### Report (Postgres)

```python
class Report(Base):
    __tablename__ = "reports"
    id                = Column(UUID, primary_key=True, default=uuid4)
    ticker            = Column(String(10), nullable=False, index=True)
    company           = Column(String, nullable=False)
    quarter           = Column(String(20))            # "Q1 2025"
    report_date       = Column(Date)
    transcript_source = Column(String)                # "edgar" | "fmp" | "alphavantage"
    raw_transcript    = Column(Text)                  # never sent to frontend
    report_json       = Column(JSONB, nullable=False) # full ReportJSON
    created_at        = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("ticker", "quarter"),
    )
```

### ReportJSON schema (what Claude must return, what the frontend consumes)

```typescript
interface ReportJSON {
  // Identity
  company:      string
  ticker:       string
  quarter:      string        // "Q1 2025"
  reportDate:   string        // "April 30, 2025"

  // Composite signal — ALL fields required
  signal:           "BUY" | "HOLD" | "WATCH"
  signalRationale:  string    // ≤ 25 words, explains final call
  signalConfidence: number    // 0–100
  signalChanged:    boolean   // true if external sources moved signal from transcript-only
  sourceSignals: {
    transcript: "BUY" | "HOLD" | "WATCH"
    news:       "BUY" | "HOLD" | "WATCH" | "MIXED" | null
    analysts:   "BUY" | "HOLD" | "WATCH" | null
    reddit:     "BULLISH" | "BEARISH" | "MIXED" | null
  }
  contradictions: string[]    // empty [] if none; max 3 items

  // Financials
  metrics: {
    revenue:         Metric
    eps:             Metric
    operatingMargin: Metric
    guidance:        Metric
  }

  // Narrative
  executiveSummary: string    // 3–4 sentences for a portfolio manager
  keyHighlights:    string[]  // exactly 5
  watchlist:        string[]  // exactly 3 items to watch next quarter

  // Risk
  risks: Array<{ text: string; level: "high" | "med" | "low" }>

  // Sentiment (transcript-derived)
  sentiment: {
    overall:        number    // 0–100
    ceoConfidence:  number
    forwardLooking: number
    caution:        number
  }

  // Management tone (transcript-derived)
  managementTone: {
    openingTone:       string
    guidanceLanguage:  string
    QATone:            string
    keyTheme:          string
  }
}

interface Metric {
  value: string    // "$24.3b"
  delta: string    // "+12% YoY"
  beat:  boolean
}
```

---

## Service contracts

### `models.py` — shared dataclass

```python
# TranscriptResult lives here (not in transcript.py) to avoid circular imports.
# edgar.py and scraper.py both import it from services.models.
@dataclass
class TranscriptResult:
    ticker:      str
    text:        str
    source:      str           # "edgar" | "fmp" | "stockanalysis"
    quarter:     str | None
    report_date: date | None
```

### `transcript.py` — waterfall fetcher

```python
async def fetch_transcript(ticker: str) -> TranscriptResult:
    """Waterfall: EDGAR → FMP → scraper. Return on first success (min 2000 chars)."""
    for source_fn in [fetch_from_edgar, fetch_from_fmp, fetch_from_motley_fool]:
        try:
            result = await source_fn(ticker)
            if result and len(result.text) >= 2000:
                return result
        except Exception:
            continue
    raise TranscriptNotFoundError(ticker)
```

### `edgar.py` — SEC EDGAR fetcher

```python
EDGAR_BASE  = "https://data.sec.gov/submissions"
HEADERS     = {"User-Agent": os.getenv("EDGAR_USER_AGENT")}

async def fetch_from_edgar(ticker: str) -> TranscriptResult | None:
    # 1. GET /submissions/{cik}.json  →  resolve ticker → CIK
    # 2. Filter recent 8-K filings (last 120 days)
    # 3. Parse filing index page with BeautifulSoup — find EX-99.1 / EX-99.2 rows by type,
    #    NOT by filename (filenames vary wildly, e.g. d729501dex991.htm)
    # 4. Fetch exhibit and validate transcript markers
    # NOTE: Most large-cap companies (AAPL, MSFT, etc.) do NOT file call transcripts
    # with the SEC — they only file press releases. EDGAR only works for companies
    # that explicitly include the transcript as an 8-K exhibit.
```

### `fmp_transcript.py` — Financial Modeling Prep fallback

```python
# Requires FMP_KEY env var. Returns None gracefully if key is absent.
# Endpoint: GET https://financialmodelingprep.com/api/v3/earning_call_transcript/{ticker}
#             ?limit=1&apikey={FMP_KEY}
# Coverage: all S&P 500 + most mid-caps. Free tier = 250 req/day.
# This is the primary source for all major tickers that don't file with EDGAR.

async def fetch_from_fmp(ticker: str) -> TranscriptResult | None: ...
```

### `scraper.py` — third-tier fallback (Alpha Vantage)

```python
# Alpha Vantage EARNINGS_CALL_TRANSCRIPT endpoint.
# Requires ALPHA_VANTAGE_KEY env var — returns None gracefully if absent.
# Tries up to 3 most recent calendar quarters; returns on first hit ≥ 2000 chars.
# Function is still named fetch_from_motley_fool for waterfall compatibility.
```

---

## Signal weighting service

### Trust weights

```python
SIGNAL_WEIGHTS = {
    "transcript": 0.40,   # primary, highest fidelity
    "news":       0.25,   # fast-moving, noisy
    "analysts":   0.25,   # lagging but structurally informed
    "reddit":     0.10,   # contrarian signal only; nudges, never decides
}
```

Reddit weight may increase to 0.20 for high-retail-interest tickers (GME, AMC, TSLA) at
Claude's discretion based on post volume — document when this happens in `contradictions`.

### `signals/aggregator.py` — fetch all sources concurrently

```python
@dataclass
class ExternalContext:
    reddit:   RedditSignal | None
    news:     NewsSignal | None
    analysts: AnalystSignal | None

async def fetch_external_context(ticker: str) -> ExternalContext:
    """
    Run all three fetchers concurrently with a 5s timeout each.
    A slow or failing source never blocks the report — it returns None
    and its weight is redistributed proportionally across available sources.
    """
    results = await asyncio.gather(
        asyncio.wait_for(fetch_reddit_sentiment(ticker), timeout=5.0),
        asyncio.wait_for(fetch_news_sentiment(ticker), timeout=5.0),
        asyncio.wait_for(fetch_analyst_ratings(ticker), timeout=5.0),
        return_exceptions=True,
    )
    reddit, news, analysts = [
        r if not isinstance(r, Exception) else None
        for r in results
    ]
    return ExternalContext(reddit=reddit, news=news, analysts=analysts)
```

### `signals/reddit.py`

```python
# Auth: OAuth2 client_credentials (no user login needed)
# Token: POST https://www.reddit.com/api/v1/access_token
#   Token is cached module-level with expiry — NOT re-fetched per call.
# Search: GET https://oauth.reddit.com/r/{sub}/search
#           ?q={ticker}&sort=top&t=week&limit=25&restrict_sr=true
SUBREDDITS   = ["investing", "stocks", "wallstreetbets"]
LOOKBACK     = "week"
MIN_SCORE    = 10

@dataclass
class RedditSignal:
    ticker:        str
    post_count:    int
    bullish_count: int
    bearish_count: int
    top_titles:    list[str]   # top 5 post titles for Claude to read
    raw_signal:    str         # "BULLISH" | "BEARISH" | "MIXED"

# What to send Claude: top_titles + ratio — NOT raw JSON.
# Claude interprets tone from titles; numbers provide context.
```

### `signals/news.py`

```python
# Primary: NewsAPI  GET https://newsapi.org/v2/everything
#            ?q={ticker}+earnings&sources=reuters,cnbc,marketwatch
#            &from={14_days_ago}&sortBy=relevancy&pageSize=10
# Fallback (no key): Reuters RSS  https://feeds.reuters.com/reuters/businessNews
#                    CNBC RSS     https://search.cnbc.com/rs/search/combinedcms/view.xml
#   feedparser.parse() is synchronous — always call via run_in_executor, never directly.

@dataclass
class NewsSignal:
    ticker:     str
    headlines:  list[str]    # max 10, most relevant
    raw_signal: str          # "BUY" | "HOLD" | "WATCH" | "MIXED"
    sources:    list[str]    # ["Reuters", "CNBC"]

# Send Claude: headlines list only. Claude infers sentiment.
# Never send full article bodies — copyright + token waste.
```

### `signals/analysts.py`

```python
# Finnhub: GET https://finnhub.io/api/v1/stock/recommendation
#            ?symbol={ticker}&token={FINNHUB_KEY}
# Returns monthly consensus: {buy, hold, sell, strongBuy, strongSell}
# Use most recent month only.

@dataclass
class AnalystSignal:
    ticker:      str
    buy:         int
    hold:        int
    sell:        int
    strong_buy:  int
    strong_sell: int
    raw_signal:  str    # computed: "BUY" | "HOLD" | "WATCH"
    period:      str    # "2025-04"

# Consensus logic:
# (buy + strong_buy) / total > 0.60  → "BUY"
# (sell + strong_sell) / total > 0.40 → "WATCH"
# else                                 → "HOLD"
```

### `analyst.py` — composite Claude prompt

```python
SYSTEM_PROMPT = """
You are an elite buy-side analyst. You receive:
  1. A full earnings call transcript (40% weight)
  2. Recent news headlines (25% weight)
  3. Analyst consensus ratings (25% weight)
  4. Reddit retail sentiment summary (10% weight)

Produce a ReportJSON. The signal field must reflect ALL sources weighted as above.

Signal adjudication rules:
- Sources agree → straightforward signal, confidence 75–95
- Transcript + analysts agree, news/Reddit diverge → keep signal, lower confidence 10–15pts,
  note divergence in contradictions[]
- Transcript vs analysts DISAGREE → this is the most important case; explain explicitly in
  signalRationale, confidence must be ≤ 60
- Reddit alone NEVER flips a signal. It lowers confidence or adds a contradictions entry.
- signalChanged = true only if final signal differs from what transcript alone would suggest
- contradictions[]: max 3 items, plain English, each ≤ 15 words

Return ONLY valid JSON. No markdown fences, no preamble. Schema is ReportJSON above.
"""

async def generate_report(
    transcript: str,
    ticker: str,
    external: ExternalContext,
) -> ReportJSON:
    # 1. Truncate transcript to 80k chars if needed
    # 2. Format external context as structured text block
    # 3. Single Claude call with transcript + external block
    # 4. Validate JSON parses to ReportJSON (all required fields present)
    # 5. Retry once on parse failure with correction prompt
```

---

## API routes

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/health`                  | `{"status":"ok"}` |
| POST   | `/analyze/{ticker}`        | Runs LangGraph agent; **returns SSE stream** — progress events then `{"type":"done","report":{...}}` |
| GET    | `/analyze/{ticker}/latest` | Return cached report JSON if < 24h old |
| GET    | `/analyze/{ticker}/history`| Last N quarters for ticker ordered newest-first (default N=6, max 12); returns `ReportJSON[]` |
| GET    | `/search?q={query}`        | FMP ticker search — `[{symbol, name, exchange}]`; results cached 1h in-memory; returns `[]` if no `FMP_KEY` |
| POST   | `/ask/{ticker}`            | `{question, history}` → Claude Q&A answer |
| GET    | `/watchlist`               | List watched tickers |
| POST   | `/watchlist/{ticker}`      | Add ticker |
| DELETE | `/watchlist/{ticker}`      | Remove ticker |

**SSE streaming:** `POST /analyze/{ticker}` returns `Content-Type: text/event-stream`. Each
event is `data: {JSON}\n\n`. Event types:
- `{"type": "progress", "message": "..."}` — one per LangGraph node (planner, fetch, analyst, reflector, formatter)
- `{"type": "done", "report": {ReportJSON}}` — final event; frontend resolves here
- `{"type": "error", "message": "...", "code": "..."}` — terminal failure

The frontend reads SSE via `fetch()` + `ReadableStream` (not `EventSource`, which requires GET).
Cache hits emit a single progress event then `done` immediately.

**Ticker validation:** All `{ticker}` path parameters are validated against `^[A-Z0-9.]{1,10}$`
before any service call. Invalid tickers return 422. Both `analyze.py` and `watchlist.py`
use a shared `_validate_ticker()` helper — add the same check to any new ticker endpoint.

**Caching rule:** Check Postgres first on every `/analyze` call. If same ticker+quarter exists
and is < 24h old, stream a cached response — no re-scrape, no Claude call, no signal fetch.
Concurrent duplicate inserts are handled via `IntegrityError` catch + rollback — do not remove.

**Error responses:** `{"error": "human-readable message", "code": "SNAKE_CASE_CODE"}`.
Never expose stack traces in production.

---

## Frontend state

```typescript
// useAnalysis owns this
interface AppState {
  currentReport:  ReportJSON | null
  history:        ReportJSON[]      // persisted to localStorage "earningslens_history", cap 20, newest first
  isLoading:      boolean
  loadingMessage: string            // driven by SSE progress events, not a timer
  error:          string | null
}

// useQA owns this
interface QAState {
  answer:    string | null
  isThinking: boolean
  history:   Array<{role: "user"|"assistant"; content: string}>
}
```

**localStorage:** `useAnalysis` persists `history` under key `"earningslens_history"` (JSON array,
max 20 entries, newest-first). Loaded via lazy `useState` initializer on mount. Written on every
new successful report. De-duplicates by `(ticker, quarter)` — same quarter replaces rather than
prepends.

`src/api.js` is the only file that calls `fetch`. Exports:
- `analyzeTickerApi(ticker, onProgress?)` → `Promise<ReportJSON>` — reads SSE stream; calls `onProgress(message)` on each progress event
- `getTickerHistoryApi(ticker, n?)` → `Promise<ReportJSON[]>` — calls `GET /analyze/{ticker}/history`
- `searchTickersApi(q)` → `Promise<{symbol, name, exchange}[]>` — calls `GET /search?q=`
- `askQuestionApi(ticker, question, history)` → `string`
- `getWatchlistApi()` → `string[]`
- `addWatchlistApi(ticker)` → `void`
- `removeWatchlistApi(ticker)` → `void`

**`<SignalBlock>`** renders the composite signal: badge, confidence bar, source breakdown row
(`T: BUY  N: HOLD  A: HOLD  R: BEARISH`), and contradiction pills in `--red` when present.

**`<TrendPanel>`** renders below the report in `<ReportView>`. Receives `ticker` prop, self-fetches
`GET /analyze/{ticker}/history` on mount, renders a 4-card grid of SVG sparklines:
- EPS Beat/Miss — colored dot per quarter (green=beat, red=miss)
- Revenue Delta — polyline, parsed from `metrics.revenue.delta` string (e.g. `"+12% YoY"`)
- Signal Confidence — polyline, 0–100
- Sentiment Overall — polyline, 0–100
Hidden entirely when `history.length < 2` (no sparkline without at least two data points).

**`<Sidebar>`** autocomplete: input debounces 300ms, fires `searchTickersApi`, shows a dropdown
of `{symbol, name, exchange}`. Selecting a suggestion immediately calls `onAnalyze(symbol)` and
clears the input. Keyboard navigation: ArrowUp/Down moves highlight, Enter selects, Escape closes.
Falls back gracefully (empty dropdown) when `FMP_KEY` is absent.

---

## Coding rules

**Python**
- Async everywhere — `httpx.AsyncClient`
- All external calls: try/except with typed errors (`TranscriptNotFoundError`, `ClaudeError`,
  `RedditError`, `NewsError`, `AnalystError`)
- No bare `except Exception` in service layer — catch, log, re-raise typed
- Never call synchronous I/O inside an async function — use `asyncio.get_event_loop().run_in_executor()`
- Always guard `response.content[0]` access: check `response.content` is non-empty and has a `.text` attribute before accessing
- Alembic for all schema changes. Never `create_all` in production.
- `ruff` for linting, `black` for formatting

**TypeScript/React**
- Functional components only. No `fetch` in components — hooks and `api.js` only.
- CSS variables for all colors. Never hardcoded hex in component files.
- Fonts: `DM Mono` for data/labels, `Playfair Display` for headings, `DM Sans` for prose.

**Git**
- Branches: `main` (prod), `dev` (working)
- Commits: `feat:`, `fix:`, `chore:`, `refactor:`
- Never commit `.env`, `*.pyc`, `node_modules/`, `dist/`

---

## Railway deployment

**Services:** `backend` · `frontend` · `postgres` (plugin)

**Backend start:** `alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`

**Frontend:** `vite build` → `dist/` → `nginx:alpine`. `VITE_API_URL` is a build-time ARG.

**Health checks:** Railway hits `/health` every 30s. Deploy fails if it doesn't return 200.

**Env vars to set in Railway dashboard:**
`DATABASE_URL` (auto), `ANTHROPIC_API_KEY`, `EDGAR_USER_AGENT`, `CORS_ORIGINS`,
`FMP_KEY`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `NEWSAPI_KEY`, `FINNHUB_KEY`

---

## What Claude should never do

- Never hardcode ticker data, fake financials, or stub transcript content in production
- Never expose `raw_transcript` in API responses — too large, unnecessary
- Never call Claude with a transcript > 100k characters without truncating first
- Never let a single slow signal source (Reddit, NewsAPI) block report generation —
  all three run with `asyncio.gather` + 5s individual timeouts
- Never let Reddit sentiment alone flip a signal — it adjusts confidence only
- Never skip `EDGAR_USER_AGENT` header — SEC will block the IP
- Never use `print()` for logging — use `logging.getLogger(__name__)`
- Never return HTTP 200 with an error payload — use proper status codes
- Never store `ANTHROPIC_API_KEY` or any third-party key in the database
- Never create a `.env.example` file — it is permanently gitignored after a credential leak; document variables in CLAUDE.md instead
- Never add a ticker endpoint without running it through `_validate_ticker()` first
- Never call `feedparser.parse()` or any other synchronous network library directly in async code
- Never match EDGAR exhibit filenames by string pattern (e.g. "99-1", "99.1") — parse the filing
  index HTML with BeautifulSoup and match the "Type" column for "EX-99.1" / "EX-99.2" instead,
  since filenames vary wildly (e.g. `d729501dex991.htm`)
- Never import `TranscriptResult` from `services.transcript` — import from `services.models` to
  avoid the circular import between transcript.py ↔ edgar.py ↔ scraper.py
- Never call agent nodes directly from routers — always go through `agent.astream` (streaming) or `agent.ainvoke`
- Never let the sufficiency loop run more than 3 iterations — enforce `state.iterations < 3` hard cap
- `langgraph` and `langchain-anthropic` are in requirements.txt; do not remove them
- Never use `EventSource` for the analyze endpoint — it only supports GET; use `fetch()` + `ReadableStream` instead
- Never pin `anthropic==X.Y.Z` in requirements.txt — `langchain-anthropic` requires a newer anthropic than 0.40; use `anthropic>=0.40.0`
- Never call `agent.astream` without `stream_mode="updates"` — default `"values"` mode doesn't yield node names, making progress events impossible
