import { useState, useCallback } from 'react';
import { analyzeTickerApi } from '../api';

const LS_KEY = 'earningslens_history';
const MAX_HISTORY = 20;

function loadHistory() {
  try {
    const stored = localStorage.getItem(LS_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

export function useAnalysis() {
  const [state, setState] = useState(() => ({
    currentReport: null,
    history: loadHistory(),
    isLoading: false,
    loadingMessage: 'Starting analysis…',
    error: null,
  }));

  const analyze = useCallback(async (ticker) => {
    setState(s => ({ ...s, isLoading: true, error: null, loadingMessage: 'Starting analysis…' }));

    try {
      const report = await analyzeTickerApi(ticker, (msg) => {
        setState(s => ({ ...s, loadingMessage: msg }));
      });

      setState(s => {
        const newHistory = [
          report,
          ...s.history.filter(r => !(r.ticker === report.ticker && r.quarter === report.quarter)),
        ].slice(0, MAX_HISTORY);
        try {
          localStorage.setItem(LS_KEY, JSON.stringify(newHistory));
        } catch {}
        return {
          ...s,
          currentReport: report,
          history: newHistory,
          isLoading: false,
          error: null,
        };
      });
    } catch (err) {
      setState(s => ({ ...s, isLoading: false, error: err.message }));
    }
  }, []);

  const selectFromHistory = useCallback((report) => {
    setState(s => ({ ...s, currentReport: report, error: null }));
  }, []);

  return { state, analyze, selectFromHistory };
}
