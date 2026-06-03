"""
Ticker normalization and static fallback search.

normalize() converts common user inputs (GOOGLE, FB, GOOG) to canonical
ticker symbols (GOOGL, META, GOOGL). Used in the analyze router before
any downstream call so every service sees the canonical ticker.

static_search() returns a filtered subset of well-known tickers when
FMP search is unavailable, giving the autocomplete dropdown something
useful to show.
"""
from __future__ import annotations

# Maps non-canonical or alias inputs → canonical ticker
_ALIASES: dict[str, str] = {
    # Alphabet
    "GOOGLE": "GOOGL",
    "GOOG":   "GOOGL",
    # Meta
    "FB":       "META",
    "FACEBOOK": "META",
    # Berkshire
    "BRKA": "BRK.A",
    "BRKB": "BRK.B",
    # Other common colloquials
    "MICROSOFT": "MSFT",
    "APPLE":     "AAPL",
    "AMAZON":    "AMZN",
    "TESLA":     "TSLA",
    "NVIDIA":    "NVDA",
    "NETFLIX":   "NFLX",
}

# Static list used for fallback autocomplete when FMP is unavailable.
# Each entry: (symbol, name, exchange)
_POPULAR: list[tuple[str, str, str]] = [
    ("AAPL",  "Apple Inc.",                    "NASDAQ"),
    ("MSFT",  "Microsoft Corporation",          "NASDAQ"),
    ("GOOGL", "Alphabet Inc. (Class A)",        "NASDAQ"),
    ("AMZN",  "Amazon.com Inc.",               "NASDAQ"),
    ("NVDA",  "NVIDIA Corporation",             "NASDAQ"),
    ("META",  "Meta Platforms Inc.",            "NASDAQ"),
    ("TSLA",  "Tesla Inc.",                     "NASDAQ"),
    ("BRK.B", "Berkshire Hathaway Inc. Cl B",  "NYSE"),
    ("BRK.A", "Berkshire Hathaway Inc. Cl A",  "NYSE"),
    ("LLY",   "Eli Lilly and Company",          "NYSE"),
    ("JPM",   "JPMorgan Chase & Co.",           "NYSE"),
    ("V",     "Visa Inc.",                      "NYSE"),
    ("UNH",   "UnitedHealth Group Inc.",        "NYSE"),
    ("XOM",   "Exxon Mobil Corporation",        "NYSE"),
    ("MA",    "Mastercard Incorporated",        "NYSE"),
    ("JNJ",   "Johnson & Johnson",              "NYSE"),
    ("PG",    "Procter & Gamble Co.",           "NYSE"),
    ("HD",    "Home Depot Inc.",                "NYSE"),
    ("AVGO",  "Broadcom Inc.",                  "NASDAQ"),
    ("COST",  "Costco Wholesale Corporation",   "NASDAQ"),
    ("MRK",   "Merck & Co. Inc.",              "NYSE"),
    ("ABBV",  "AbbVie Inc.",                    "NYSE"),
    ("CRM",   "Salesforce Inc.",               "NYSE"),
    ("AMD",   "Advanced Micro Devices Inc.",    "NASDAQ"),
    ("NFLX",  "Netflix Inc.",                   "NASDAQ"),
    ("ACN",   "Accenture plc",                  "NYSE"),
    ("LIN",   "Linde plc",                      "NYSE"),
    ("MCD",   "McDonald's Corporation",         "NYSE"),
    ("ADBE",  "Adobe Inc.",                     "NASDAQ"),
    ("TXN",   "Texas Instruments Inc.",         "NASDAQ"),
    ("WMT",   "Walmart Inc.",                   "NYSE"),
    ("PM",    "Philip Morris International",    "NYSE"),
    ("BAC",   "Bank of America Corporation",    "NYSE"),
    ("QCOM",  "Qualcomm Inc.",                  "NASDAQ"),
    ("ORCL",  "Oracle Corporation",             "NYSE"),
    ("GE",    "GE Aerospace",                   "NYSE"),
    ("NOW",   "ServiceNow Inc.",               "NYSE"),
    ("INTC",  "Intel Corporation",              "NASDAQ"),
    ("IBM",   "IBM Corporation",               "NYSE"),
    ("GS",    "Goldman Sachs Group Inc.",       "NYSE"),
    ("RTX",   "RTX Corporation",               "NYSE"),
    ("DE",    "Deere & Company",               "NYSE"),
    ("SPGI",  "S&P Global Inc.",              "NYSE"),
    ("CAT",   "Caterpillar Inc.",              "NYSE"),
    ("BKNG",  "Booking Holdings Inc.",         "NASDAQ"),
    ("PFE",   "Pfizer Inc.",                   "NYSE"),
    ("LOW",   "Lowe's Companies Inc.",         "NYSE"),
    ("AXP",   "American Express Company",      "NYSE"),
    ("CVX",   "Chevron Corporation",           "NYSE"),
    ("MS",    "Morgan Stanley",                "NYSE"),
    ("AMT",   "American Tower Corporation",    "NYSE"),
    ("GILD",  "Gilead Sciences Inc.",          "NASDAQ"),
    ("INTU",  "Intuit Inc.",                   "NASDAQ"),
    ("UBER",  "Uber Technologies Inc.",        "NYSE"),
    ("SHOP",  "Shopify Inc.",                  "NYSE"),
    ("SQ",    "Block Inc.",                    "NYSE"),
    ("PLTR",  "Palantir Technologies Inc.",    "NYSE"),
    ("COIN",  "Coinbase Global Inc.",          "NASDAQ"),
    ("RBLX",  "Roblox Corporation",            "NYSE"),
    ("SNOW",  "Snowflake Inc.",               "NYSE"),
    ("ARM",   "Arm Holdings plc",             "NASDAQ"),
    ("SMCI",  "Super Micro Computer Inc.",     "NASDAQ"),
]


def normalize(ticker: str) -> str:
    """Return the canonical ticker for a given input (uppercased, alias-resolved)."""
    upper = ticker.strip().upper()
    return _ALIASES.get(upper, upper)


def static_search(query: str, limit: int = 8) -> list[dict]:
    """Filter _POPULAR by query prefix or substring match on symbol or name."""
    q = query.strip().upper()
    if not q:
        return []

    results = []
    # Exact or prefix match on symbol first
    for sym, name, exch in _POPULAR:
        if sym.startswith(q) or sym == _ALIASES.get(q, q):
            results.append({"symbol": sym, "name": name, "exchange": exch})

    # Then substring match on name (avoid duplicates)
    seen = {r["symbol"] for r in results}
    q_lower = query.strip().lower()
    for sym, name, exch in _POPULAR:
        if sym not in seen and q_lower in name.lower():
            results.append({"symbol": sym, "name": name, "exchange": exch})
            seen.add(sym)

    return results[:limit]
