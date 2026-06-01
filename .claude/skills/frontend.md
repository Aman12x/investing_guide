# Frontend Skill — EarningsLens

## Stack
- Vite + React (JSX, no TypeScript)
- CSS variables for all colors (never hardcoded hex in components)
- Fonts: `DM Mono` (data/labels), `Playfair Display` (headings), `DM Sans` (prose)

## Structure
```
frontend/src/
├── main.jsx
├── App.jsx
├── api.js                  # ALL fetch calls live here — single source of truth
├── components/
│   ├── Sidebar.jsx
│   ├── ReportView.jsx
│   ├── MetricsGrid.jsx
│   ├── SignalBlock.jsx      # composite signal badge + confidence + source breakdown
│   ├── SentimentBars.jsx
│   ├── RiskList.jsx
│   ├── ManagementTone.jsx
│   ├── QABar.jsx
│   ├── EmailModal.jsx
│   └── Toast.jsx
├── hooks/
│   ├── useAnalysis.js       # owns AppState
│   └── useQA.js             # owns QAState
└── pages/
    └── Home.jsx
```

## Rules

**Components**
- Functional components only — no class components
- No `fetch` calls inside components — use hooks and `api.js`
- All colors via CSS variables — never inline hex values

**api.js exports** (the only file that calls `fetch`):
- `analyzeTickerApi(ticker)` → `ReportJSON`
- `askQuestionApi(ticker, question, history)` → `string`
- `saveSubscriptionApi(config)` → `void`
- `getSubscriptionApi()` → `SubscriptionConfig | null`

**State shape**

```js
// useAnalysis owns:
{
  currentReport:  ReportJSON | null,
  history:        ReportJSON[],   // session only, newest first
  isLoading:      boolean,
  loadingMessage: string,
  error:          string | null,
}

// useQA owns:
{
  answer:     string | null,
  isThinking: boolean,
  history:    [{role: "user"|"assistant", content: string}],
}
```

## SignalBlock component
Receives the full `ReportJSON`. Renders:
1. Signal badge (`BUY` / `HOLD` / `WATCH`)
2. Confidence bar (0–100)
3. Source breakdown row: `T: BUY  N: HOLD  A: HOLD  R: BEARISH`
4. Contradiction pills in `var(--red)` when `contradictions[]` is non-empty

## Dev server
```bash
cd frontend && npm install && npm run dev
# runs on http://localhost:3000
# VITE_API_URL=http://localhost:8000 (set in frontend/.env)
```

## Build (production)
```bash
vite build   # outputs to dist/
# served by nginx:alpine — see frontend/nginx.conf
# VITE_API_URL is a build-time ARG injected by Railway
```

## When working on frontend tasks
1. Start the dev server first (`npm run dev` in `frontend/`)
2. Test the golden path (analyze a ticker, view report, ask a Q&A question)
3. Check `SignalBlock` renders all four source signals correctly
4. Verify no hardcoded colors — only CSS variables
5. Confirm no `fetch` calls leaked into component files
