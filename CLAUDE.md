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
├── docker-compose.prod.yml
├── .gitignore
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # FastAPI app, CORS
│   ├── database.py               # SQLAlchemy engine + session
│   ├── models.py                 # ORM: Report, Watchlist, QASession
│   ├── routers/
│   │   ├── analyze.py            # POST /analyze/{ticker}
│   │   ├── ask.py                # POST /ask/{ticker}
│   │   └── watchlist.py          # GET/POST/DELETE /watchlist
│   ├── services/
│   │   ├── transcript.py         # Waterfall: EDGAR → scraper
│   │   ├── edgar.py              # SEC EDGAR 8-K fetcher
│   │   ├── scraper.py            # Motley Fool fallback
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
        │   ├── Sidebar.jsx
        │   ├── ReportView.jsx
        │   ├── MetricsGrid.jsx
        │   ├── SignalBlock.jsx    # Signal badge + confidence + source breakdown
        │   ├── SentimentBars.jsx
        │   ├── RiskList.jsx
        │   ├── ManagementTone.jsx
        │   ├── QABar.jsx
        │   └── Toast.jsx
        ├── hooks/
        │   ├── useAnalysis.js
        │   └── useQA.js
        └── pages/
            └── Home.jsx
```

---

## Environment variables

```bash
# backend/.env  ← lives here, never committed, no .env.example (permanently gitignored)
DATABASE_URL=postgresql://user:pass@localhost:5432/earningslens
ANTHROPIC_API_KEY=sk-ant-...
EDGAR_USER_AGENT="EarningsLens yourname@email.com"   # required by SEC fair-use policy
SCRAPER_DELAY_MS=1500                                  # politeness delay between scrape requests
CORS_ORIGINS=http://localhost:3000,https://yourapp.up.railway.app

# External signal sources
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
NEWSAPI_KEY=...                                        # newsapi.org free tier = 100 req/day
FINNHUB_KEY=...                                        # free tier = 60 req/min

# frontend/.env
VITE_API_URL=http://localhost:8000
```

**Rules:**
- Every secret is an env var. No hardcoded URLs, keys, or credentials anywhere in code.
- Never create `.env.example` — it is permanently blocked in `.gitignore`. Document variables here instead.
- Railway auto-injects `DATABASE_URL` — `database.py` must rewrite `postgres://` → `postgresql://`.
- `EDGAR_USER_AGENT` is not optional. SEC will block requests without it.
- All four signal source keys are optional — if absent, that source is skipped gracefully and
  confidence is recalculated across remaining sources.

---

## Core data contracts

### Report (Postgres)

```python
class Report(Base):
    __tablename__ = "reports"
    id                = Column(UUID, primary_key=True, default=uuid4)
    ticker            = Column(String(10), nullable=False, index=True)
    company           = Column(String, nullable=False)
    quarter           = Column(String(20))            # "Q1 2025"
    report_date       = Column(Date)
    transcript_source = Column(String)                # "edgar" | "motley_fool"
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

### `transcript.py` — waterfall fetcher

```python
async def fetch_transcript(ticker: str) -> TranscriptResult:
    """Try sources in order. Return on first success (min 2000 chars)."""
    for source_fn in [fetch_from_edgar, fetch_from_motley_fool]:
        try:
            result = await source_fn(ticker)
            if result and len(result.text) > 2000:
                return result
        except Exception:
            continue
    raise TranscriptNotFoundError(ticker)

@dataclass
class TranscriptResult:
    ticker:      str
    text:        str
    source:      str           # "edgar" | "motley_fool"
    quarter:     str | None
    report_date: date | None
```

### `edgar.py` — SEC EDGAR fetcher

```python
EDGAR_BASE  = "https://data.sec.gov/submissions"
SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"
HEADERS     = {"User-Agent": os.getenv("EDGAR_USER_AGENT")}

async def fetch_from_edgar(ticker: str) -> TranscriptResult | None:
    # 1. GET /submissions/{cik}.json  →  resolve ticker → CIK
    # 2. Filter recent 8-K filings
    # 3. Check exhibits 99.1 / 99.2 for transcript markers
    #    ("operator", "question-and-answer", speaker turn patterns)
    # 4. Fetch and return exhibit text
```

### `scraper.py` — Motley Fool fallback

```python
# URL pattern: https://www.fool.com/earnings/call-transcripts/{yyyy}/{mm}/{dd}/
#              {ticker}-q{n}-{yyyy}-earnings-call-transcript/
POLITENESS_DELAY = float(os.getenv("SCRAPER_DELAY_MS", 1500)) / 1000

async def fetch_from_motley_fool(ticker: str) -> TranscriptResult | None:
    # 1. Resolve latest transcript URL
    # 2. GET with realistic headers (User-Agent, Accept-Language)
    # 3. BeautifulSoup — strip nav/ads, return article body
    # 4. Validate transcript markers
    # 5. await asyncio.sleep(POLITENESS_DELAY)
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
| POST   | `/analyze/{ticker}`        | Transcript + signals → composite report → cache |
| GET    | `/analyze/{ticker}/latest` | Return cached report if < 24h old |
| POST   | `/ask/{ticker}`            | `{question, history}` → Claude Q&A answer |
| GET    | `/watchlist`               | List watched tickers |
| POST   | `/watchlist/{ticker}`      | Add ticker |
| DELETE | `/watchlist/{ticker}`      | Remove ticker |

**Ticker validation:** All `{ticker}` path parameters are validated against `^[A-Z0-9.]{1,10}$`
before any service call. Invalid tickers return 422. Both `analyze.py` and `watchlist.py`
use a shared `_validate_ticker()` helper — add the same check to any new ticker endpoint.

**Caching rule:** Check Postgres first on every `/analyze` call. If same ticker+quarter exists
and is < 24h old, return cached report — no re-scrape, no Claude call, no signal fetch.
Concurrent duplicate inserts are handled via `IntegrityError` catch + rollback — do not remove.

**Error responses:** `{"error": "human-readable message", "code": "SNAKE_CASE_CODE"}`.
Never expose stack traces in production.

---

## Frontend state

```typescript
// useAnalysis owns this
interface AppState {
  currentReport:  ReportJSON | null
  history:        ReportJSON[]      // session only, newest first
  isLoading:      boolean
  loadingMessage: string
  error:          string | null
}

// useQA owns this
interface QAState {
  answer:    string | null
  isThinking: boolean
  history:   Array<{role: "user"|"assistant"; content: string}>
}
```

`src/api.js` is the only file that calls `fetch`. Exports:
- `analyzeTickerApi(ticker)` → `ReportJSON`
- `askQuestionApi(ticker, question, history)` → `string`
- `getWatchlistApi()` → `string[]`
- `addWatchlistApi(ticker)` → `void`
- `removeWatchlistApi(ticker)` → `void`

**`<SignalBlock>`** is the new component that renders the composite signal. It receives the full
`ReportJSON` and renders: signal badge, confidence bar, source breakdown row
(`T: BUY  N: HOLD  A: HOLD  R: BEARISH`), and contradiction pills in `--red` when present.

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
`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `NEWSAPI_KEY`, `FINNHUB_KEY`

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
