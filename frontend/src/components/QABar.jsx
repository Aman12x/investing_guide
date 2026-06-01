import { useState } from 'react';
import styles from './QABar.module.css';

const SUGGESTIONS = [
  'Forward guidance',
  'Key risks',
  'vs. expectations',
  'CEO priorities',
  'Language red flags',
  'Growth segments',
];

export default function QABar({ ticker, visible, answer, isThinking, onAsk }) {
  const [input, setInput] = useState('');

  if (!visible) return null;

  function handleSubmit(e) {
    e.preventDefault();
    const q = input.trim();
    if (!q || isThinking) return;
    onAsk(q);
    setInput('');
  }

  function handleChip(suggestion) {
    if (isThinking) return;
    onAsk(suggestion);
    setInput('');
  }

  return (
    <div className={styles.bar}>
      <p className={styles.sectionLabel}>Ask about {ticker}</p>

      <form className={styles.inputRow} onSubmit={handleSubmit}>
        <input
          className={styles.input}
          type="text"
          placeholder="Ask a follow-up question…"
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={isThinking}
        />
        <button className={styles.askBtn} type="submit" disabled={isThinking || !input.trim()}>
          Ask
        </button>
      </form>

      <div className={styles.chips}>
        {SUGGESTIONS.map(s => (
          <button
            key={s}
            className={styles.chip}
            onClick={() => handleChip(s)}
            disabled={isThinking}
          >
            {s}
          </button>
        ))}
      </div>

      {(answer || isThinking) && (
        <div className={`${styles.answer} ${answer ? 'report-enter' : ''}`}>
          {isThinking
            ? <span className="loading-message">Analyzing…</span>
            : <p>{answer}</p>
          }
        </div>
      )}
    </div>
  );
}
