const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export async function analyzeTickerApi(ticker) {
  const res = await fetch(`${BASE}/analyze/${ticker}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `Analysis failed (${res.status})`);
  }
  return res.json();
}

export async function askQuestionApi(ticker, question, history) {
  const res = await fetch(`${BASE}/ask/${ticker}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history }),
  });
  if (!res.ok) throw new Error('Q&A request failed');
  const data = await res.json();
  return data.answer;
}

export async function saveSubscriptionApi(config) {
  const res = await fetch(`${BASE}/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('Failed to save subscription');
}

export async function getSubscriptionApi() {
  const res = await fetch(`${BASE}/schedule`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error('Failed to fetch subscription');
  return res.json();
}

export async function getWatchlistApi() {
  const res = await fetch(`${BASE}/watchlist`);
  if (!res.ok) throw new Error('Failed to fetch watchlist');
  return res.json();
}

export async function addWatchlistApi(ticker) {
  const res = await fetch(`${BASE}/watchlist/${ticker}`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to add to watchlist');
}

export async function removeWatchlistApi(ticker) {
  const res = await fetch(`${BASE}/watchlist/${ticker}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to remove from watchlist');
}
