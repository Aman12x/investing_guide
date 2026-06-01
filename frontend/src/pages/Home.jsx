import { useState } from 'react';
import { useAnalysis } from '../hooks/useAnalysis';
import { useQA } from '../hooks/useQA';
import Sidebar from '../components/Sidebar';
import ReportView from '../components/ReportView';
import EmptyState from '../components/EmptyState';
import QABar from '../components/QABar';
import Toast from '../components/Toast';
import styles from './Home.module.css';

export default function Home() {
  const { state, analyze, selectFromHistory } = useAnalysis();
  const { currentReport, history, isLoading, loadingMessage, error } = state;
  const { answer, isThinking, ask } = useQA(currentReport?.ticker);

  const [toast, setToast] = useState('');

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <span className={styles.headerBrand}>EarningsLens</span>
        {currentReport && (
          <div className={styles.toolbar}>
            <span className={styles.reportLabel}>
              {currentReport.ticker} — {currentReport.quarter}
            </span>
          </div>
        )}
      </header>

      <div className={styles.body}>
        <Sidebar
          history={history}
          currentReport={currentReport}
          onSelect={selectFromHistory}
          onAnalyze={analyze}
          isLoading={isLoading}
        />

        <div className={styles.content}>
          <div className={styles.contentScroll}>
            {isLoading && (
              <div className={styles.loadingOverlay}>
                <div className={`${styles.spinner} spinner`} />
                <p className={`${styles.loadingMsg} loading-message`}>{loadingMessage}</p>
              </div>
            )}

            {!isLoading && error && (
              <div className={styles.errorState}>
                <p className={styles.errorText}>{error}</p>
              </div>
            )}

            {!isLoading && !error && !currentReport && <EmptyState />}

            {!isLoading && !error && currentReport && (
              <ReportView report={currentReport} />
            )}
          </div>

          <QABar
            ticker={currentReport?.ticker}
            visible={!!currentReport && !isLoading}
            answer={answer}
            isThinking={isThinking}
            onAsk={q => ask(q)}
          />
        </div>
      </div>

      <Toast message={toast} onDismiss={() => setToast('')} />
    </div>
  );
}
