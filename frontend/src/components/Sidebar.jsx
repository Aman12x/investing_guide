import { useState } from 'react';
import styles from './Sidebar.module.css';

const QUICK_CHIPS = ['AAPL', 'MSFT', 'NVDA', 'META', 'GOOGL', 'AMZN'];

export default function Sidebar({ history, currentReport, onSelect, onAnalyze, isLoading }) {
  const [input, setInput] = useState('');

  function handleSubmit(e) {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker) return;
    onAnalyze(ticker);
    setInput('');
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandName}>EarningsLens</span>
      </div>

      <form className={styles.searchForm} onSubmit={handleSubmit}>
        <input
          className={styles.searchInput}
          type="text"
          placeholder="Enter ticker…"
          value={input}
          onChange={e => setInput(e.target.value.toUpperCase())}
          maxLength={10}
          disabled={isLoading}
          autoCapitalize="characters"
        />
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
