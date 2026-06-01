import { useEffect, useRef, useState } from 'react';
import styles from './SentimentBars.module.css';

const BARS = [
  { key: 'overall', label: 'Overall' },
  { key: 'ceoConfidence', label: 'CEO Confidence' },
  { key: 'forwardLooking', label: 'Forward Looking' },
  { key: 'caution', label: 'Caution' },
];

function barClass(val) {
  if (val >= 65) return styles.barGreen;
  if (val >= 45) return styles.barGold;
  return styles.barRed;
}

export default function SentimentBars({ sentiment }) {
  const [widths, setWidths] = useState({});
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    requestAnimationFrame(() => {
      if (mounted.current) {
        const w = {};
        BARS.forEach(({ key }) => { w[key] = sentiment?.[key] ?? 0; });
        setWidths(w);
      }
    });
    return () => { mounted.current = false; };
  }, [sentiment]);

  return (
    <div className={styles.wrap}>
      <p className={styles.heading}>Sentiment</p>
      {BARS.map(({ key, label }) => (
        <div key={key} className={styles.row}>
          <span className={styles.label}>{label}</span>
          <div className={styles.track}>
            <div
              className={`${styles.fill} bar-fill ${barClass(sentiment?.[key] ?? 0)}`}
              style={{ width: `${widths[key] ?? 0}%` }}
            />
          </div>
          <span className={styles.val}>{sentiment?.[key] ?? 0}</span>
        </div>
      ))}
    </div>
  );
}
