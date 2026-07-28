import React, { useState, useRef, useEffect, useCallback } from "react";
import { Send, ChevronDown, Loader2, AlertCircle, Settings2, X, FileStack, Newspaper, BookOpen } from "lucide-react";


const EXAMPLE_QUESTIONS = [
  "What does UnitedHealth describe as risk factors tied to its regulatory environment?",
  "What is Apple's stated services revenue for fiscal 2024?",
  "How does Caterpillar's debt trajectory compare to its operating profit?",
];

const EXAMPLE_NEWS = [
  { ticker: "AVGO", headline: "Broadcom announces $10B share repurchase program" },
  { ticker: "MSFT", headline: "Microsoft Azure revenue grows 35% in Q2, beating estimates" },
  { ticker: "ASML", headline: "Netherlands expands export controls on advanced chip equipment to China" },
];

function useAutoResize(ref, value) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = Math.min(el.scrollHeight, 168) + "px";
  }, [ref, value]);
}

function Citation({ chunk, isOpen, onToggle }) {
  return (
    <div className={"edrd-chip-wrap" + (isOpen ? " is-open" : "")}>
      <button
        className="edrd-chip"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <span className="edrd-chip-tab" aria-hidden="true" />
        {chunk.citation}
        <ChevronDown className="edrd-chip-caret" size={12} strokeWidth={2.5} />
      </button>
      {isOpen && (
        <div className="edrd-source" role="region">
          <div className="edrd-source-meta">
            <span>{chunk.ticker}</span>
            <span className="edrd-dot" />
            <span>{chunk.filing_type}</span>
            <span className="edrd-dot" />
            <span>{chunk.filed_date}</span>
            <span className="edrd-dot" />
            <span>similarity {chunk.similarity?.toFixed(3)}</span>
          </div>
          <div className="edrd-source-path">
            {Array.isArray(chunk.section_path) ? chunk.section_path.join(" › ") : chunk.section_path}
          </div>
          <p className="edrd-source-text">{chunk.content_preview}</p>
        </div>
      )}
    </div>
  );
}

function AssistantMessage({ msg }) {
  const [openId, setOpenId] = useState(null);
  const chunks = msg.chunks || [];

  return (
    <div className="edrd-row edrd-row-assistant">
      <div className="edrd-card">
        <p className="edrd-answer">{msg.answer}</p>
        {chunks.length > 0 && (
          <div className="edrd-citations">
            <div className="edrd-citations-label">
              <FileStack size={12} strokeWidth={2.5} />
              {chunks.length} source{chunks.length === 1 ? "" : "s"}
            </div>
            <div className="edrd-chips">
              {chunks.map((c, i) => (
                <Citation
                  key={i}
                  chunk={c}
                  isOpen={openId === i}
                  onToggle={() => setOpenId(openId === i ? null : i)}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function NewsAssessmentMessage({ msg }) {
  return (
    <div className="edrd-row edrd-row-assistant">
      <div className="edrd-card edrd-card-news">
        <div className="edrd-news-header">
          <Newspaper size={14} strokeWidth={2} />
          <span className="edrd-news-ticker">{msg.ticker}</span>
        </div>
        <pre className="edrd-assessment">{msg.assessment}</pre>
      </div>
    </div>
  );
}

function ErrorMessage({ text, onRetry }) {
  return (
    <div className="edrd-row edrd-row-assistant">
      <div className="edrd-card edrd-card-error">
        <div className="edrd-error-head">
          <AlertCircle size={15} strokeWidth={2.25} />
          Couldn't reach the research desk
        </div>
        <p className="edrd-error-text">{text}</p>
        {onRetry && (
          <button className="edrd-retry" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export default function EdgarResearchDesk() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiBase, setApiBase] = useState("http://localhost:8000");
  const [showSettings, setShowSettings] = useState(false);
  const [tickerFilter, setTickerFilter] = useState("");
  const [filingType, setFilingType] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [mode, setMode] = useState("qa");
  const [newsTicker, setNewsTicker] = useState("");

  const textareaRef = useRef(null);
  const scrollRef = useRef(null);
  const lastQuestionRef = useRef("");
  const lastNewsRef = useRef({ ticker: "", headline: "" });

  useAutoResize(textareaRef, input);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const ask = useCallback(
    async (question) => {
      if (!question.trim() || loading) return;
      lastQuestionRef.current = question;
      setMessages((m) => [...m, { role: "user", text: question }]);
      setInput("");
      setLoading(true);

      const body = { question, k: 8 };
      const tickers = tickerFilter
        .split(",")
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean);
      if (tickers.length) body.tickers = tickers;
      if (filingType) body.filing_types = [filingType];

      try {
        const res = await fetch(`${apiBase}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          throw new Error(`${res.status} ${res.statusText}${detail ? " — " + detail.slice(0, 200) : ""}`);
        }
        const data = await res.json();
        setMessages((m) => [
          ...m,
          { role: "assistant", answer: data.answer, chunks: data.chunks || [] },
        ]);
      } catch (err) {
        const msg =
          err.message?.includes("Failed to fetch") || err.name === "TypeError"
            ? `No response from ${apiBase}. Confirm the API is running and CORS is enabled for this origin.`
            : err.message;
        setMessages((m) => [...m, { role: "error", text: msg }]);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, loading, tickerFilter, filingType]
  );

  const assessNews = useCallback(
    async (ticker, headline) => {
      if (!ticker.trim() || !headline.trim() || loading) return;
      lastNewsRef.current = { ticker, headline };
      setMessages((m) => [...m, { role: "user", text: `[${ticker.toUpperCase()}] ${headline}` }]);
      setInput("");
      setLoading(true);

      try {
        const res = await fetch(`${apiBase}/news-assess`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker: ticker.trim().toUpperCase(), headline: headline.trim() }),
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          throw new Error(`${res.status} ${res.statusText}${detail ? " — " + detail.slice(0, 200) : ""}`);
        }
        const data = await res.json();
        setMessages((m) => [
          ...m,
          { role: "news-assessment", ticker: data.ticker, assessment: data.assessment },
        ]);
      } catch (err) {
        const msg =
          err.message?.includes("Failed to fetch") || err.name === "TypeError"
            ? `No response from ${apiBase}. Confirm the API is running and CORS is enabled for this origin.`
            : err.message;
        setMessages((m) => [...m, { role: "error", text: msg }]);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, loading]
  );

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (mode === "qa") {
        ask(input);
      } else {
        assessNews(newsTicker, input);
      }
    }
  };

  const retry = () => {
    setMessages((m) => m.slice(0, -1));
    if (mode === "qa") {
      ask(lastQuestionRef.current);
    } else {
      assessNews(lastNewsRef.current.ticker, lastNewsRef.current.headline);
    }
  };

  return (
    <div className="edrd-root">
      <style>{`
        .edrd-root {
          --bg: #15171b;
          --surface: #1e2126;
          --surface-raised: #262a30;
          --line: #2d3138;
          --ink: #ece7db;
          --ink-dim: #8c8f96;
          --brass: #c9a227;
          --brass-dim: #8a7420;
          --brick: #a65a43;
          --teal: #2a9d8f;
          --teal-dim: #1e7268;

          min-height: 100vh;
          background: var(--bg);
          color: var(--ink);
          display: flex;
          flex-direction: column;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        }

        .edrd-header {
          border-bottom: 1px solid var(--line);
          padding: 22px 24px 18px;
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 16px;
        }

        .edrd-brand {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .edrd-brand-mark {
          font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
          font-size: 19px;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--ink);
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .edrd-brand-mark::before {
          content: "";
          width: 8px;
          height: 8px;
          border-radius: 1px;
          background: var(--brass);
          transform: rotate(45deg);
          flex-shrink: 0;
        }

        .edrd-brand-sub {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11px;
          letter-spacing: 0.04em;
          color: var(--ink-dim);
          padding-left: 18px;
        }

        .edrd-header-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .edrd-settings-btn {
          background: none;
          border: 1px solid var(--line);
          color: var(--ink-dim);
          border-radius: 6px;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          flex-shrink: 0;
          transition: border-color 0.15s, color 0.15s;
        }
        .edrd-settings-btn:hover { border-color: var(--brass-dim); color: var(--ink); }
        .edrd-settings-btn:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }

        .edrd-settings-panel {
          border-bottom: 1px solid var(--line);
          background: var(--surface);
          padding: 14px 24px;
          display: flex;
          gap: 20px;
          flex-wrap: wrap;
          align-items: center;
          font-size: 12.5px;
        }

        .edrd-mode-bar {
          border-bottom: 1px solid var(--line);
          background: var(--surface);
          padding: 0 24px;
          display: flex;
          gap: 0;
        }

        .edrd-mode-tab {
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          color: var(--ink-dim);
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11.5px;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          padding: 11px 16px 9px;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: color 0.15s, border-color 0.15s;
        }
        .edrd-mode-tab:hover { color: var(--ink); }
        .edrd-mode-tab.is-active {
          color: var(--brass);
          border-bottom-color: var(--brass);
        }
        .edrd-mode-tab.is-active-news {
          color: var(--teal);
          border-bottom-color: var(--teal);
        }

        .edrd-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .edrd-field label {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 10.5px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--ink-dim);
        }

        .edrd-field input, .edrd-field select {
          background: var(--surface-raised);
          border: 1px solid var(--line);
          color: var(--ink);
          border-radius: 5px;
          padding: 6px 9px;
          font-size: 13px;
          font-family: inherit;
          min-width: 200px;
        }
        .edrd-field select { min-width: 110px; }
        .edrd-field input:focus-visible, .edrd-field select:focus-visible {
          outline: 2px solid var(--brass);
          outline-offset: 1px;
          border-color: var(--brass-dim);
        }

        .edrd-thread {
          flex: 1;
          overflow-y: auto;
          padding: 28px 24px 12px;
          display: flex;
          flex-direction: column;
          gap: 18px;
        }

        .edrd-empty {
          margin: auto;
          max-width: 440px;
          text-align: center;
          padding: 40px 20px;
        }

        .edrd-empty-mark {
          font-family: Georgia, "Iowan Old Style", serif;
          font-size: 15px;
          color: var(--ink-dim);
          margin-bottom: 6px;
          letter-spacing: 0.02em;
        }

        .edrd-empty-sub {
          font-size: 13px;
          color: var(--ink-dim);
          line-height: 1.6;
          margin-bottom: 22px;
        }

        .edrd-examples {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .edrd-example-btn {
          text-align: left;
          background: var(--surface);
          border: 1px solid var(--line);
          color: var(--ink);
          border-radius: 8px;
          padding: 11px 14px;
          font-size: 13px;
          font-family: inherit;
          cursor: pointer;
          transition: border-color 0.15s, background 0.15s;
          line-height: 1.45;
        }
        .edrd-example-btn:hover { border-color: var(--brass-dim); background: var(--surface-raised); }
        .edrd-example-btn:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }

        .edrd-example-btn-news {
          text-align: left;
          background: var(--surface);
          border: 1px solid var(--line);
          color: var(--ink);
          border-radius: 8px;
          padding: 11px 14px;
          font-size: 13px;
          font-family: inherit;
          cursor: pointer;
          transition: border-color 0.15s, background 0.15s;
          line-height: 1.45;
        }
        .edrd-example-btn-news:hover { border-color: var(--teal-dim); background: var(--surface-raised); }
        .edrd-example-btn-news:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }
        .edrd-example-btn-news .edrd-example-ticker {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 10.5px;
          color: var(--teal);
          letter-spacing: 0.04em;
          margin-bottom: 2px;
        }

        .edrd-row { display: flex; width: 100%; }
        .edrd-row-user { justify-content: flex-end; }
        .edrd-row-assistant { justify-content: flex-start; }

        .edrd-user-bubble {
          max-width: 72%;
          background: var(--surface-raised);
          border: 1px solid var(--line);
          border-radius: 10px 10px 2px 10px;
          padding: 11px 15px;
          font-size: 14.5px;
          line-height: 1.55;
        }

        .edrd-card {
          max-width: 78%;
          background: var(--surface);
          border: 1px solid var(--line);
          border-left: 2px solid var(--brass);
          border-radius: 3px 10px 10px 3px;
          padding: 16px 18px;
        }

        .edrd-card-news {
          border-left-color: var(--teal);
          max-width: 85%;
        }

        .edrd-card-error { border-left-color: var(--brick); max-width: 78%; }

        .edrd-news-header {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--teal);
          font-size: 12px;
          font-weight: 600;
          margin-bottom: 10px;
        }

        .edrd-news-ticker {
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11.5px;
          letter-spacing: 0.06em;
        }

        .edrd-assessment {
          font-size: 13.5px;
          line-height: 1.7;
          white-space: pre-wrap;
          word-wrap: break-word;
          margin: 0;
          font-family: inherit;
          color: var(--ink);
        }

        .edrd-answer {
          font-size: 14.5px;
          line-height: 1.65;
          white-space: pre-wrap;
          margin: 0;
        }

        .edrd-citations { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line); }

        .edrd-citations-label {
          display: flex;
          align-items: center;
          gap: 6px;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 10.5px;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--ink-dim);
          margin-bottom: 9px;
        }

        .edrd-chips { display: flex; flex-direction: column; gap: 6px; }

        .edrd-chip-wrap { display: flex; flex-direction: column; }

        .edrd-chip {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          align-self: flex-start;
          background: transparent;
          border: 1px solid var(--brass-dim);
          color: var(--brass);
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 11.5px;
          letter-spacing: 0.02em;
          padding: 5px 9px 5px 6px;
          border-radius: 4px;
          cursor: pointer;
          position: relative;
          transition: background 0.15s, color 0.15s;
        }
        .edrd-chip-tab {
          width: 4px;
          height: 12px;
          background: var(--brass-dim);
          border-radius: 1px;
          flex-shrink: 0;
        }
        .edrd-chip:hover { background: rgba(201, 162, 39, 0.1); }
        .edrd-chip:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }
        .edrd-chip-wrap.is-open .edrd-chip { background: rgba(201, 162, 39, 0.12); color: #e2c25e; }
        .edrd-chip-wrap.is-open .edrd-chip-tab { background: var(--brass); }
        .edrd-chip-caret { transition: transform 0.15s; }
        .edrd-chip-wrap.is-open .edrd-chip-caret { transform: rotate(180deg); }

        .edrd-source {
          margin: 6px 0 4px 4px;
          padding: 10px 13px;
          background: var(--surface-raised);
          border: 1px solid var(--line);
          border-radius: 6px;
          font-size: 12.5px;
        }

        .edrd-source-meta {
          display: flex;
          align-items: center;
          gap: 8px;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 10.5px;
          color: var(--ink-dim);
          margin-bottom: 6px;
        }
        .edrd-dot { width: 2px; height: 2px; background: var(--ink-dim); border-radius: 50%; }

        .edrd-source-path {
          font-size: 11px;
          color: var(--brass);
          margin-bottom: 7px;
          letter-spacing: 0.01em;
        }

        .edrd-source-text {
          color: var(--ink-dim);
          line-height: 1.55;
          margin: 0;
        }

        .edrd-error-head {
          display: flex;
          align-items: center;
          gap: 7px;
          color: var(--brick);
          font-size: 13.5px;
          font-weight: 600;
          margin-bottom: 5px;
        }
        .edrd-error-text { font-size: 13px; color: var(--ink-dim); line-height: 1.5; margin: 0 0 10px; }
        .edrd-retry {
          background: none;
          border: 1px solid var(--brick);
          color: var(--brick);
          border-radius: 5px;
          padding: 5px 12px;
          font-size: 12px;
          font-family: inherit;
          cursor: pointer;
        }
        .edrd-retry:hover { background: rgba(166, 90, 67, 0.12); }

        .edrd-thinking {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--ink-dim);
          font-size: 12.5px;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          padding: 4px 2px;
        }
        .edrd-thinking svg { animation: edrd-spin 0.9s linear infinite; }

        @keyframes edrd-spin { to { transform: rotate(360deg); } }

        .edrd-composer {
          border-top: 1px solid var(--line);
          padding: 14px 24px 18px;
          background: var(--bg);
        }

        .edrd-filters-toggle {
          background: none;
          border: none;
          color: var(--ink-dim);
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 10.5px;
          letter-spacing: 0.05em;
          text-transform: uppercase;
          cursor: pointer;
          padding: 0 0 8px;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .edrd-filters-toggle:hover { color: var(--ink); }
        .edrd-filters-toggle svg { transition: transform 0.15s; }
        .edrd-filters-toggle.is-open svg { transform: rotate(180deg); }

        .edrd-filters-row {
          display: flex;
          gap: 12px;
          margin-bottom: 10px;
          flex-wrap: wrap;
        }

        .edrd-news-inputs {
          display: flex;
          gap: 10px;
          margin-bottom: 10px;
          align-items: flex-end;
        }

        .edrd-news-ticker-field input {
          min-width: 90px;
          max-width: 100px;
          text-transform: uppercase;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 13px;
          letter-spacing: 0.04em;
        }

        .edrd-input-bar {
          display: flex;
          align-items: flex-end;
          gap: 10px;
          background: var(--surface);
          border: 1px solid var(--line);
          border-radius: 10px;
          padding: 8px 8px 8px 14px;
        }
        .edrd-input-bar:focus-within { border-color: var(--brass-dim); }
        .edrd-input-bar.is-news:focus-within { border-color: var(--teal-dim); }

        .edrd-prompt-glyph {
          color: var(--brass);
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
          font-size: 15px;
          padding-bottom: 9px;
          flex-shrink: 0;
        }
        .edrd-prompt-glyph.is-news { color: var(--teal); }

        .edrd-textarea {
          flex: 1;
          background: none;
          border: none;
          color: var(--ink);
          font-family: inherit;
          font-size: 14.5px;
          line-height: 1.5;
          resize: none;
          outline: none;
          padding: 8px 0;
          max-height: 168px;
        }
        .edrd-textarea::placeholder { color: var(--ink-dim); }

        .edrd-send {
          flex-shrink: 0;
          width: 34px;
          height: 34px;
          border-radius: 8px;
          border: none;
          background: var(--brass);
          color: #1a1c20;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: opacity 0.15s, transform 0.1s;
        }
        .edrd-send.is-news { background: var(--teal); }
        .edrd-send:hover:not(:disabled) { opacity: 0.88; }
        .edrd-send:active:not(:disabled) { transform: scale(0.94); }
        .edrd-send:disabled { opacity: 0.35; cursor: not-allowed; }
        .edrd-send:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }

        .edrd-hint {
          font-size: 10.5px;
          color: var(--ink-dim);
          margin-top: 8px;
          font-family: ui-monospace, "SF Mono", Menlo, monospace;
        }

        @media (max-width: 640px) {
          .edrd-header { padding: 16px 16px 14px; }
          .edrd-thread { padding: 20px 14px 8px; }
          .edrd-composer { padding: 12px 14px 14px; }
          .edrd-card, .edrd-user-bubble { max-width: 92%; }
          .edrd-card-news { max-width: 96%; }
          .edrd-news-inputs { flex-direction: column; gap: 8px; }
          .edrd-news-ticker-field input { max-width: 100%; min-width: 100%; }
        }

        @media (prefers-reduced-motion: reduce) {
          .edrd-thinking svg { animation: none; }
          * { transition: none !important; }
        }
      `}</style>

      <header className="edrd-header">
        <div className="edrd-brand">
          <div className="edrd-brand-mark">Edgar Research Desk</div>
          <div className="edrd-brand-sub">grounded Q&amp;A over SEC filings — every claim cited</div>
        </div>
        <div className="edrd-header-actions">
          <button
            className="edrd-settings-btn"
            onClick={() => setShowSettings((s) => !s)}
            aria-label="Settings"
            aria-expanded={showSettings}
          >
            {showSettings ? <X size={15} /> : <Settings2 size={15} />}
          </button>
        </div>
      </header>

      {showSettings && (
        <div className="edrd-settings-panel">
          <div className="edrd-field">
            <label htmlFor="edrd-api-base">API base URL</label>
            <input
              id="edrd-api-base"
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="http://localhost:8000"
            />
          </div>
        </div>
      )}

      <div className="edrd-mode-bar">
        <button
          className={"edrd-mode-tab" + (mode === "qa" ? " is-active" : "")}
          onClick={() => setMode("qa")}
        >
          <BookOpen size={13} strokeWidth={2} />
          Filing Q&A
        </button>
        <button
          className={"edrd-mode-tab" + (mode === "news" ? " is-active-news" : "")}
          onClick={() => setMode("news")}
        >
          <Newspaper size={13} strokeWidth={2} />
          News Assessment
        </button>
      </div>

      <div className="edrd-thread" ref={scrollRef}>
        {messages.length === 0 && mode === "qa" && (
          <div className="edrd-empty">
            <div className="edrd-empty-mark">Nothing on the desk yet</div>
            <p className="edrd-empty-sub">
              Ask about revenue, risk factors, debt, or anything else disclosed in an ingested filing.
              Every answer cites the exact section it came from.
            </p>
            <div className="edrd-examples">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button key={q} className="edrd-example-btn" onClick={() => ask(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.length === 0 && mode === "news" && (
          <div className="edrd-empty">
            <div className="edrd-empty-mark">News assessment desk</div>
            <p className="edrd-empty-sub">
              Enter a ticker and news headline to get an assessment grounded in SEC filings
              and your watchlist thesis. The agent cross-references the news against filing
              disclosures and returns a verdict.
            </p>
            <div className="edrd-examples">
              {EXAMPLE_NEWS.map((ex) => (
                <button
                  key={ex.headline}
                  className="edrd-example-btn-news"
                  onClick={() => {
                    setNewsTicker(ex.ticker);
                    assessNews(ex.ticker, ex.headline);
                  }}
                >
                  <div className="edrd-example-ticker">{ex.ticker}</div>
                  {ex.headline}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) =>
          msg.role === "user" ? (
            <div className="edrd-row edrd-row-user" key={i}>
              <div className="edrd-user-bubble">{msg.text}</div>
            </div>
          ) : msg.role === "error" ? (
            <ErrorMessage key={i} text={msg.text} onRetry={i === messages.length - 1 ? retry : undefined} />
          ) : msg.role === "news-assessment" ? (
            <NewsAssessmentMessage key={i} msg={msg} />
          ) : (
            <AssistantMessage key={i} msg={msg} />
          )
        )}

        {loading && (
          <div className="edrd-row edrd-row-assistant">
            <div className="edrd-thinking">
              <Loader2 size={13} strokeWidth={2.5} />
              {mode === "news" ? "assessing news against filings…" : "retrieving filings…"}
            </div>
          </div>
        )}
      </div>

      <div className="edrd-composer">
        {mode === "qa" && (
          <>
            <button
              className={"edrd-filters-toggle" + (showFilters ? " is-open" : "")}
              onClick={() => setShowFilters((s) => !s)}
            >
              <ChevronDown size={11} strokeWidth={2.5} />
              filters {tickerFilter || filingType ? "· active" : ""}
            </button>

            {showFilters && (
              <div className="edrd-filters-row">
                <div className="edrd-field">
                  <label htmlFor="edrd-tickers">Tickers</label>
                  <input
                    id="edrd-tickers"
                    type="text"
                    value={tickerFilter}
                    onChange={(e) => setTickerFilter(e.target.value)}
                    placeholder="AAPL, UNH, CAT"
                  />
                </div>
                <div className="edrd-field">
                  <label htmlFor="edrd-form">Form type</label>
                  <select id="edrd-form" value={filingType} onChange={(e) => setFilingType(e.target.value)}>
                    <option value="">Any</option>
                    <option value="10-K">10-K</option>
                    <option value="10-Q">10-Q</option>
                  </select>
                </div>
              </div>
            )}
          </>
        )}

        {mode === "news" && (
          <div className="edrd-news-inputs">
            <div className="edrd-field edrd-news-ticker-field">
              <label htmlFor="edrd-news-ticker">Ticker</label>
              <input
                id="edrd-news-ticker"
                type="text"
                value={newsTicker}
                onChange={(e) => setNewsTicker(e.target.value.toUpperCase())}
                placeholder="AVGO"
              />
            </div>
          </div>
        )}

        <div className={"edrd-input-bar" + (mode === "news" ? " is-news" : "")}>
          <span className={"edrd-prompt-glyph" + (mode === "news" ? " is-news" : "")}>›</span>
          <textarea
            ref={textareaRef}
            className="edrd-textarea"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === "news" ? "Enter a news headline…" : "Ask about a filing…"}
            rows={1}
          />
          <button
            className={"edrd-send" + (mode === "news" ? " is-news" : "")}
            onClick={() => mode === "qa" ? ask(input) : assessNews(newsTicker, input)}
            disabled={mode === "qa" ? !input.trim() || loading : !input.trim() || !newsTicker.trim() || loading}
            aria-label={mode === "news" ? "Assess news" : "Send question"}
          >
            <Send size={15} strokeWidth={2.25} />
          </button>
        </div>
        <div className="edrd-hint">
          {mode === "news"
            ? "Enter ticker above, headline below · Enter to assess"
            : "Enter to send · Shift+Enter for a new line"}
        </div>
      </div>
    </div>
  );
}
