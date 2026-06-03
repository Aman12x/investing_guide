import { useState, useEffect, useRef, useCallback } from 'react';
import { searchTickersApi } from '../api';
import styles from './Sidebar.module.css';

const QUICK_CHIPS = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL', 'AMZN'];

function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function Sidebar({ history, currentReport, onSelect, onAnalyze, isLoading }) {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const wrapRef = useRef(null);
  const debouncedInput = useDebounce(input, 300);

  useEffect(() => {
    if (!debouncedInput || debouncedInput.length < 1) {
      setSuggestions([]);
      setOpen(false);
      return;
    }
    searchTickersApi(debouncedInput)
      .then(res => {
        setSuggestions(res);
        setOpen(res.length > 0);
        setActiveIdx(-1);
      })
      .catch(() => { setSuggestions([]); setOpen(false); });
  }, [debouncedInput]);

  useEffect(() => {
    function onClickOutside(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const selectSuggestion = useCallback((symbol) => {
    setInput('');
    setSuggestions([]);
    setOpen(false);
    onAnalyze(symbol);
  }, [onAnalyze]);

  function handleSubmit(e) {
    e.preventDefault();
    if (activeIdx >= 0 && suggestions[activeIdx]) {
      selectSuggestion(suggestions[activeIdx].symbol);
      return;
    }
    const ticker = input.trim().toUpperCase();
    if (!ticker) return;
    setInput('');
    setOpen(false);
    onAnalyze(ticker);
  }

  function handleKeyDown(e) {
    if (!open) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx(i => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx(i => Math.max(i - 1, -1));
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandName}>EarningsLens</span>
      </div>

      <form className={styles.searchForm} onSubmit={handleSubmit}>
        <div className={styles.comboWrap} ref={wrapRef}>
          <input
            className={styles.searchInput}
            type="text"
            placeholder="Ticker or company…"
            value={input}
            onChange={e => setInput(e.target.value.toUpperCase())}
            onKeyDown={handleKeyDown}
            onFocus={() => suggestions.length > 0 && setOpen(true)}
            maxLength={50}
            disabled={isLoading}
            autoCapitalize="characters"
            autoComplete="off"
          />
          {open && suggestions.length > 0 && (
            <ul className={styles.dropdown}>
              {suggestions.map((s, i) => (
                <li
                  key={s.symbol}
                  className={`${styles.dropdownItem} ${i === activeIdx ? styles.dropdownActive : ''}`}
                  onMouseDown={() => selectSuggestion(s.symbol)}
                >
                  <span className={styles.dropSymbol}>{s.symbol}</span>
                  <span className={styles.dropName}>{s.name}</span>
                  {s.exchange && <span className={styles.dropExchange}>{s.exchange}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
        <button className={styles.analyzeBtn} type="submit" disabled={isLoading || !input.trim()}>
          {isLoading ? 'Analyzing…' : 'Analyze'}
        </button>
      </form>

      <div className={styles.chips}>
        {QUICK_CHIPS.map(t => (
          <button
            key={t}
            className={styles.chip}
            onClick={() => onAnalyze(t)}
            disabled={isLoading}
          >
            {t}
          </button>
        ))}
      </div>

      {history.length > 0 && (
        <div className={styles.historySection}>
          <p className={styles.historyLabel}>Recent</p>
          <ul className={styles.historyList}>
            {history.map(r => (
              <li
                key={r.ticker + r.quarter}
                className={`${styles.historyItem} ${currentReport?.ticker === r.ticker ? styles.active : ''}`}
                onClick={() => onSelect(r)}
              >
                <span className={styles.historyTicker}>{r.ticker}</span>
                <span className={styles.historyQuarter}>{r.quarter}</span>
                <span className={`${styles.signalChip} ${styles[r.signal?.toLowerCase()]}`}>
                  {r.signal}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
