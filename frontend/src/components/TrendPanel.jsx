import { useState, useEffect } from 'react';
import { getTickerHistoryApi } from '../api';
import styles from './TrendPanel.module.css';

function parsePercent(delta) {
  if (!delta) return null;
  const m = delta.match(/([+-]?\d+(?:\.\d+)?)\s*%/);
  return m ? parseFloat(m[1]) : null;
}

function Sparkline({ values, min, max, height = 36 }) {
  const W = 160, H = height, PAD = 4;
  const n = values.length;
  if (n < 2) return null;

  const lo = min ?? Math.min(...values);
  const hi = max ?? Math.max(...values);
  const range = hi - lo || 1;

  const points = values.map((v, i) => {
    const x = PAD + (i / (n - 1)) * (W - 2 * PAD);
    const y = H - PAD - ((v - lo) / range) * (H - 2 * PAD);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className={styles.svg}>
      <polyline points={points} fill="none" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function BeatDots({ values }) {
  const W = 160, H = 20, PAD = 8;
  const n = values.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className={styles.svg}>
      {values.map((beat, i) => {
        const x = n === 1 ? W / 2 : PAD + (i / (n - 1)) * (W - 2 * PAD);
        const fill = beat === true ? 'var(--green)' : beat === false ? 'var(--red)' : 'var(--border)';
        return <circle key={i} cx={x.toFixed(1)} cy={H / 2} r={4} fill={fill} />;
      })}
    </svg>
  );
}

function QuarterLabels({ quarters }) {
  return (
    <div className={styles.labels}>
      {quarters.map((q, i) => (
        <span key={i} className={styles.qLabel}>{q}</span>
      ))}
    </div>
  );
}

export default function TrendPanel({ ticker }) {
  const [history, setHistory] = useState([]);

  useEffect(() => {
    if (!ticker) return;
    getTickerHistoryApi(ticker, 6)
      .then(data => setHistory([...data].reverse()))
      .catch(() => setHistory([]));
  }, [ticker]);

  if (history.length < 2) return null;

  const quarters = history.map(r => {
    const q = r.quarter ?? '';
    return q.replace(/(\d{4})/, (_, y) => `'${y.slice(2)}`);
  });

  const epsBeat = history.map(r => r.metrics?.eps?.beat ?? null);
  const confidences = history.map(r => r.signalConfidence ?? 0);
  const sentiments = history.map(r => r.sentiment?.overall ?? 0);

  // Only include quarters where a parseable revenue delta exists, so null entries
  // never get imputed as 0 and rendered outside the sparkline's min/max bounds.
  const revEntries = history
    .map((r, i) => ({ delta: parsePercent(r.metrics?.revenue?.delta), quarter: quarters[i] }))
    .filter(e => e.delta !== null);
  const revValues = revEntries.map(e => e.delta);
  const revQuarters = revEntries.map(e => e.quarter);
  const revMin = revValues.length ? Math.min(...revValues) : -20;
  const revMax = revValues.length ? Math.max(...revValues) : 20;
  const latestRev = revValues.length ? revValues[revValues.length - 1] : null;

  const latestConf = confidences[confidences.length - 1];
  const latestSent = sentiments[sentiments.length - 1];

  return (
    <div className={styles.panel}>
      <p className={styles.heading}>Multi-Quarter Trend</p>
      <div className={styles.grid}>

        <div className={styles.card}>
          <p className={styles.cardLabel}>EPS Beat / Miss</p>
          <BeatDots values={epsBeat} />
          <QuarterLabels quarters={quarters} />
        </div>

        <div className={styles.card}>
          <p className={styles.cardLabel}>Revenue Delta</p>
          {revValues.length >= 2 ? (
            <Sparkline
              values={revValues}
              min={revMin - 2}
              max={revMax + 2}
            />
          ) : (
            <div className={styles.noData}>Not enough data</div>
          )}
          <div className={styles.latestRow}>
            <QuarterLabels quarters={revQuarters} />
            {latestRev !== null && (
              <span className={`${styles.latestVal} ${latestRev >= 0 ? styles.pos : styles.neg}`}>
                {latestRev >= 0 ? '+' : ''}{latestRev}%
              </span>
            )}
          </div>
        </div>

        <div className={styles.card}>
          <p className={styles.cardLabel}>Signal Confidence</p>
          <Sparkline values={confidences} min={0} max={100} />
          <div className={styles.latestRow}>
            <QuarterLabels quarters={quarters} />
            <span className={styles.latestVal}>{latestConf}</span>
          </div>
        </div>

        <div className={styles.card}>
          <p className={styles.cardLabel}>Sentiment (Overall)</p>
          <Sparkline values={sentiments} min={0} max={100} />
          <div className={styles.latestRow}>
            <QuarterLabels quarters={quarters} />
            <span className={styles.latestVal}>{latestSent}</span>
          </div>
        </div>

      </div>
    </div>
  );
}
