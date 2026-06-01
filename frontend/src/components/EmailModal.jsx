import { useState } from 'react';
import { saveSubscriptionApi } from '../api';
import styles from './EmailModal.module.css';

export default function EmailModal({ open, onClose, onConfirm, ticker }) {
  const [email, setEmail] = useState('');
  const [schedule, setSchedule] = useState('earnings_day');
  const [format, setFormat] = useState('summary');
  const [emailError, setEmailError] = useState('');
  const [loading, setLoading] = useState(false);

  if (!open) return null;

  async function handleConfirm() {
    if (!email.trim() || !email.includes('@')) {
      setEmailError('Enter a valid email address');
      return;
    }
    setEmailError('');
    setLoading(true);
    try {
      await saveSubscriptionApi({ email, tickers: [ticker], schedule, format });
      onConfirm();
    } catch (err) {
      setEmailError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <h2 className={styles.title}>Email Delivery</h2>
          <button className={styles.closeBtn} onClick={onClose}>×</button>
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>Email address</label>
          <input
            className={`${styles.input} ${emailError ? styles.inputError : ''}`}
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={e => { setEmail(e.target.value); setEmailError(''); }}
          />
          {emailError && <p className={styles.error}>{emailError}</p>}
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>Schedule</label>
          <select className={styles.select} value={schedule} onChange={e => setSchedule(e.target.value)}>
            <option value="now">Send now</option>
            <option value="daily">Daily digest</option>
            <option value="weekly">Weekly summary</option>
            <option value="earnings_day">On earnings day</option>
          </select>
        </div>

        <div className={styles.field}>
          <label className={styles.fieldLabel}>Format</label>
          <select className={styles.select} value={format} onChange={e => setFormat(e.target.value)}>
            <option value="summary">Executive summary</option>
            <option value="full">Full report</option>
            <option value="bullets">Bullet highlights</option>
          </select>
        </div>

        <div className={styles.actions}>
          <button className={styles.cancelBtn} onClick={onClose}>Cancel</button>
          <button className={styles.confirmBtn} onClick={handleConfirm} disabled={loading}>
            {loading ? 'Saving…' : 'Save & Subscribe'}
          </button>
        </div>
      </div>
    </div>
  );
}
