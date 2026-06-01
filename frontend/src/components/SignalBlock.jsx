import { useEffect, useRef, useState } from 'react';
import styles from './SignalBlock.module.css';

const SOURCE_LABELS = { transcript: 'T', news: 'N', analysts: 'A', reddit: 'R' };

function confidenceClass(val) {
  if (val >= 70) return styles.barGreen;
  if (val >= 45) return styles.barGold;
  return styles.barRed;
}

export default function SignalBlock({ report }) {
  const [barWidth, setBarWidth] = useState(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    requestAnimationFrame(() => {
      if (mounted.current) setBarWidth(report.signalConfidence ?? 0);
    });
    return () => { mounted.current = false; };
  }, [report.signalConfidence]);

  const signalCls = styles[report.signal?.toLowerCase()] ?? styles.hold;

  return (
    <div className={styles.block}>
      <div className={styles.topRow}>
        <span className={`${styles.badge} ${signalCls}`}>{report.signal}</span>
        <div className={styles.confidenceWrap}>
          <div className={styles.bar}>
            <div
              className={`${styles.barFill} bar-fill ${confidenceClass(report.signalConfidence)}`}
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <span className={styles.confNum}>{report.signalConfidence} / 100</span>
        </div>
      </div>

      {report.signalChanged && (
        <p className={styles.changed}>
          ▲ Signal adjusted from transcript-only call
        </p>
      )}

      <p className={styles.rationale}>{report.signalRationale}</p>

      <div className={styles.sources}>
        {Object.entries(SOURCE_LABELS).map(([key, label]) => {
          const val = report.sourceSignals?.[key];
          return (
            <span key={key} className={styles.sourceItem}>
              <span className={styles.sourceLabel}>{label}:</span>
              <span className={val ? styles[val.toLowerCase()] : styles.nullVal}>
                {val ?? '—'}
              </span>
            </span>
          );
        })}
      </div>

      {report.contradictions?.length > 0 && (
        <div className={styles.pills}>
          {report.contradictions.map((c, i) => (
            <span key={i} className={styles.pill}>⚠ {c}</span>
          ))}
        </div>
      )}
    </div>
  );
}
