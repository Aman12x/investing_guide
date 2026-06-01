import styles from './RiskList.module.css';

export default function RiskList({ items = [], level }) {
  return (
    <ul className={styles.list}>
      {items.map((item, i) => {
        const itemLevel = level ?? item.level ?? 'med';
        const text = typeof item === 'string' ? item : item.text;
        return (
          <li key={i} className={`${styles.item} ${styles[itemLevel]}`}>
            <span className={styles.levelLabel}>{itemLevel.toUpperCase()}</span>
            <span className={styles.text}>{text}</span>
          </li>
        );
      })}
    </ul>
  );
}
