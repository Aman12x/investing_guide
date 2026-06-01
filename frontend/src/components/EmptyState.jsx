import styles from './EmptyState.module.css';

export default function EmptyState() {
  return (
    <div className={styles.wrap}>
      <h1 className={styles.headline}>Read every earnings call.</h1>
      <p className={styles.sub}>
        Enter a ticker in the sidebar to pull the latest transcript, weight it against
        analyst ratings, news, and Reddit sentiment, and get an institutional-grade signal in seconds.
      </p>
      <div className={styles.hints}>
        <span className={styles.hint}>Try <strong>AAPL</strong></span>
        <span className={styles.hint}>Try <strong>NVDA</strong></span>
        <span className={styles.hint}>Try <strong>META</strong></span>
      </div>
    </div>
  );
}
