import styles from './MetricsGrid.module.css';

const METRIC_LABELS = {
  revenue: 'Revenue',
  eps: 'EPS',
  operatingMargin: 'Op. Margin',
  guidance: 'Guidance',
};

export default function MetricsGrid({ metrics }) {
  return (
    <div className={styles.grid}>
      {Object.entries(METRIC_LABELS).map(([key, label]) => {
        const m = metrics?.[key];
        return (
          <div key={key} className={styles.card}>
            <p className={styles.label}>{label}</p>
            <p className={styles.value}>{m?.value ?? '—'}</p>
            <p className={`${styles.delta} ${m?.beat === true ? styles.beat : m?.beat === false ? styles.miss : ''}`}>
              {m?.beat === true ? '▲ Beat' : m?.beat === false ? '▼ Missed' : ''} {m?.delta ?? ''}
            </p>
          </div>
        );
      })}
    </div>
  );
}
