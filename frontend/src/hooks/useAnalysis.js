import { useState, useCallback } from 'react';
import { analyzeTickerApi } from '../api';

const LOADING_MESSAGES = [
  'Fetching latest earnings transcript…',
  'Parsing revenue & guidance figures…',
  'Pulling Reddit and news signals…',
  'Weighing analyst consensus…',
  'Generating composite report…',
];

export function useAnalysis() {
  const [state, setState] = useState({
    currentReport: null,
    history: [],
    isLoading: false,
    loadingMessage: LOADING_MESSAGES[0],
    error: null,
  });

  const analyze = useCallback(async (ticker) => {
    setState(s => ({ ...s, isLoading: true, error: null, loadingMessage: LOADING_MESSAGES[0] }));

    let idx = 0;
    const cycle = setInterval(() => {
      idx = Math.min(idx + 1, LOADING_MESSAGES.length - 1);
      setState(s => ({ ...s, loadingMessage: LOADING_MESSAGES[idx] }));
    }, 2000);

    try {
      const report = await analyzeTickerApi(ticker);
      setState(s => ({
        ...s,
        currentReport: report,
        history: [report, ...s.history.filter(r => r.ticker !== report.ticker)].slice(0, 10),
        isLoading: false,
        error: null,
      }));
    } catch (err) {
      setState(s => ({ ...s, isLoading: false, error: err.message }));
    } finally {
      clearInterval(cycle);
    }
  }, []);

  const selectFromHistory = useCallback((report) => {
    setState(s => ({ ...s, currentReport: report, error: null }));
  }, []);

  return { state, analyze, selectFromHistory };
}
