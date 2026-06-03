import SignalBlock from './SignalBlock';
import MetricsGrid from './MetricsGrid';
import SentimentBars from './SentimentBars';
import ManagementTone from './ManagementTone';
import RiskList from './RiskList';
import TrendPanel from './TrendPanel';
import styles from './ReportView.module.css';

export default function ReportView({ report }) {
  return (
    <div className={`${styles.wrap} report-enter`}>
      <div className={styles.identity}>
        <h1 className={styles.company}>{report.company}</h1>
        <span className={styles.meta}>
          <span className={styles.ticker}>{report.ticker}</span>
          <span className={styles.dot}>·</span>
          <span>{report.quarter}</span>
          <span className={styles.dot}>·</span>
          <span>{report.reportDate}</span>
        </span>
      </div>

      <SignalBlock report={report} />

      <MetricsGrid metrics={report.metrics} />

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Executive Summary</p>
        <blockquote className={styles.summary}>{report.executiveSummary}</blockquote>
      </div>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Key Highlights</p>
        <RiskList items={report.keyHighlights ?? []} level="low" />
      </div>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Risk Flags</p>
        <RiskList items={report.risks ?? []} />
      </div>

      <div className={styles.twoCol}>
        <SentimentBars sentiment={report.sentiment} />
        <ManagementTone tone={report.managementTone} />
      </div>

      {report.watchlist?.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Watch Next Quarter</p>
          <RiskList items={report.watchlist} level="med" />
        </div>
      )}

      <TrendPanel ticker={report.ticker} />
    </div>
  );
}
