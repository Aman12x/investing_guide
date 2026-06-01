import styles from './ManagementTone.module.css';

const CELLS = [
  { key: 'openingTone', label: 'Opening Tone' },
  { key: 'guidanceLanguage', label: 'Guidance Language' },
  { key: 'QATone', label: 'Q&A Tone' },
  { key: 'keyTheme', label: 'Call Theme' },
];

export default function ManagementTone({ tone }) {
  return (
    <div className={styles.wrap}>
      <p className={styles.heading}>Management Tone</p>
      <div className={styles.grid}>
        {CELLS.map(({ key, label }) => (
          <div key={key} className={styles.cell}>
            <p className={styles.label}>{label}</p>
            <p className={styles.value}>{tone?.[key] ?? '—'}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
