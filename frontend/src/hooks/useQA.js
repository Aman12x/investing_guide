import { useState, useEffect, useCallback } from 'react';
import { askQuestionApi } from '../api';

export function useQA(currentTicker) {
  const [answer, setAnswer] = useState(null);
  const [isThinking, setIsThinking] = useState(false);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    setAnswer(null);
    setHistory([]);
  }, [currentTicker]);

  const ask = useCallback(async (question) => {
    if (!currentTicker) return;
    setIsThinking(true);
    const newHistory = [...history, { role: 'user', content: question }];
    setHistory(newHistory);
    try {
      const text = await askQuestionApi(currentTicker, question, newHistory);
      setHistory(h => [...h, { role: 'assistant', content: text }]);
      setAnswer(text);
    } catch {
      setAnswer('Unable to answer — please try again.');
    } finally {
      setIsThinking(false);
    }
  }, [currentTicker, history]);

  return { answer, isThinking, history, ask };
}
