const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export async function analyzeTickerApi(ticker, onProgress) {
  const res = await fetch(`${BASE}/analyze/${ticker}`, { method: 'POST' });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `Analysis failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (event.type === 'progress' && onProgress) {
        onProgress(event.message);
      } else if (event.type === 'done') {
        return event.report;
      } else if (event.type === 'error') {
        throw new Error(event.message ?? 'Analysis failed');
      }
    }
  }

  throw new Error('Stream ended without a report');
}

export async function getTickerHistoryApi(ticker, n = 6) {
  const res = await fetch(`${BASE}/analyze/${ticker}/history?n=${n}`);
  if (!res.ok) return [];
  return res.json();
}

export async function searchTickersApi(q) {
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) return [];
  return res.json();
}

export async function askQuestionApi(ticker, question, history) {
  const res = await fetch(`${BASE}/ask/${ticker}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, history }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `Q&A request failed (${res.status})`);
  }
  const data = await res.json();
  return data.answer;
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
