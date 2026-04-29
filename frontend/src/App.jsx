import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createConversation,
  createMessage,
  deleteConversation,
  getConversation,
  listConversations,
  queryV1
} from "./api";
import ChatView from "./components/ChatView";
import ConversationsView from "./components/ConversationsView";

const DEFAULT_COMPANY = "601";
const EXAMPLE_QUESTIONS = [
  "Which responders closed the most alarms last month?",
  "Show alarms with the longest resolution time this week.",
  "What are the top 5 clients by alarm volume?",
  "How many alarms were created in the last 24 hours?"
];
const NAV_ITEMS = [
  { id: "chat", label: "Query" },
  { id: "conversations", label: "Conversations" }
];

function parseCompanyId(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export default function App() {
  const [mode, setMode] = useState("chat");
  const [companyId, setCompanyId] = useState(DEFAULT_COMPANY);

  const [question, setQuestion] = useState("");
  const [queryResult, setQueryResult] = useState(null);
  const [queryError, setQueryError] = useState(null);
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [queryProgress, setQueryProgress] = useState(null);

  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messageText, setMessageText] = useState("");
  const [messageError, setMessageError] = useState(null);
  const [loadingConversation, setLoadingConversation] = useState(false);

  const activeConversationIdRef = useRef(null);
  const companyIdNumber = useMemo(() => parseCompanyId(companyId), [companyId]);

  const resultRowCount = useMemo(() => {
    if (!queryResult) {
      return 0;
    }
    return Array.isArray(queryResult.results) ? queryResult.results.length : 0;
  }, [queryResult]);

  useEffect(() => {
    activeConversationIdRef.current = activeConversation?.conversation?.id ?? null;
  }, [activeConversation]);

  useEffect(() => {
    setQueryError(null);
    setMessageError(null);
  }, [mode]);

  const selectConversation = useCallback(
    async (id) => {
      if (!companyIdNumber) {
        setMessageError("Please provide a valid company ID.");
        return;
      }

      setLoadingConversation(true);
      try {
        const data = await getConversation(id, companyIdNumber);
        setActiveConversation(data);
      } catch (err) {
        setMessageError(err.message);
      } finally {
        setLoadingConversation(false);
      }
    },
    [companyIdNumber]
  );

  const loadConversations = useCallback(async () => {
    if (!companyIdNumber) {
      setConversations([]);
      setActiveConversation(null);
      setMessageError("Please provide a valid company ID.");
      return;
    }

    try {
      const data = await listConversations(companyIdNumber);
      setConversations(data);

      const preferredId = activeConversationIdRef.current;
      const hasPreferred = preferredId && data.some((conv) => conv.id === preferredId);
      const targetId = hasPreferred ? preferredId : data[0]?.id;

      if (targetId) {
        await selectConversation(targetId);
      } else {
        setActiveConversation(null);
      }
    } catch (err) {
      setMessageError(err.message);
    }
  }, [companyIdNumber, selectConversation]);

  useEffect(() => {
    if (mode === "conversations") {
      void loadConversations();
    }
  }, [mode, loadConversations]);

  const handleChatQuery = useCallback(
    async (event) => {
      event.preventDefault();

      const trimmedQuestion = question.trim();
      if (!trimmedQuestion) {
        setQueryError("Please enter a question.");
        return;
      }
      if (!companyIdNumber) {
        setQueryError("Please provide a valid company ID.");
        return;
      }

      setLoadingQuery(true);
      setQueryError(null);
      setQueryResult(null);
      setQueryProgress({ message: "Running…", elapsed: 0 });

      const startedAt = performance.now();
      const tickId = setInterval(() => {
        setQueryProgress((prev) => ({
          message: prev?.message || "Running…",
          elapsed: (performance.now() - startedAt) / 1000
        }));
      }, 100);

      try {
        const data = await queryV1(trimmedQuestion, companyIdNumber);
        setQueryResult(data);
      } catch (err) {
        setQueryError(err.message);
      } finally {
        clearInterval(tickId);
        setLoadingQuery(false);
        setQueryProgress(null);
      }
    },
    [companyIdNumber, question]
  );

  const handleCreateConversation = useCallback(async () => {
    if (!companyIdNumber) {
      setMessageError("Please provide a valid company ID.");
      return;
    }

    try {
      const data = await createConversation(companyIdNumber);
      setConversations((prev) => [data, ...prev]);
      await selectConversation(data.id);
    } catch (err) {
      setMessageError(err.message);
    }
  }, [companyIdNumber, selectConversation]);

  const handleDeleteConversation = useCallback(
    async (id) => {
      if (!companyIdNumber) {
        setMessageError("Please provide a valid company ID.");
        return;
      }

      try {
        await deleteConversation(id, companyIdNumber);
        const next = conversations.filter((c) => c.id !== id);
        setConversations(next);

        const nextId = next[0]?.id;
        if (nextId) {
          await selectConversation(nextId);
        } else {
          setActiveConversation(null);
        }
      } catch (err) {
        setMessageError(err.message);
      }
    },
    [companyIdNumber, conversations, selectConversation]
  );

  const handleSendMessage = useCallback(
    async (event) => {
      event.preventDefault();

      const trimmedMessage = messageText.trim();
      if (!activeConversation || !trimmedMessage) {
        return;
      }
      if (!companyIdNumber) {
        setMessageError("Please provide a valid company ID.");
        return;
      }

      setLoadingConversation(true);
      setMessageError(null);
      try {
        await createMessage(activeConversation.conversation.id, companyIdNumber, trimmedMessage);
        setMessageText("");
        await selectConversation(activeConversation.conversation.id);
      } catch (err) {
        setMessageError(err.message);
      } finally {
        setLoadingConversation(false);
      }
    },
    [activeConversation, companyIdNumber, messageText, selectConversation]
  );

  return (
    <div className="app">
      <header className="hero">
        <div className="hero__content">
          <p className="eyebrow">Seon History</p>
          <h1>Signal Intelligence Console</h1>
          <p className="lead">
            Fast conversational analytics for alarm intelligence. Ask a question, inspect the SQL, and track
            conversations per customer.
          </p>
          <div className="hero__badges">
            <span className="badge">Realtime insights</span>
            <span className="badge badge--soft">Scoped by company</span>
            <span className="badge badge--outline">SQL validated</span>
          </div>
        </div>
        <div className="hero__panel">
          <div className="hero__panel-top">
            <label className="field">
              <span>Company ID</span>
              <input value={companyId} onChange={(e) => setCompanyId(e.target.value)} />
            </label>
            <div className="panel-meta">
              <span className="panel-meta__label">Active mode</span>
              <strong>{mode === "chat" ? "Query" : "Conversations"}</strong>
            </div>
          </div>
          <nav className="tabs">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                className={mode === item.id ? "tab tab--active" : "tab"}
                onClick={() => setMode(item.id)}
              >
                {item.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {mode === "chat" ? (
        <ChatView
          question={question}
          setQuestion={setQuestion}
          queryResult={queryResult}
          queryError={queryError}
          loadingQuery={loadingQuery}
          queryProgress={queryProgress}
          resultRowCount={resultRowCount}
          exampleQuestions={EXAMPLE_QUESTIONS}
          onSubmit={handleChatQuery}
        />
      ) : (
        <ConversationsView
          conversations={conversations}
          activeConversation={activeConversation}
          loadingConversation={loadingConversation}
          messageError={messageError}
          messageText={messageText}
          setMessageText={setMessageText}
          onCreateConversation={handleCreateConversation}
          onDeleteConversation={handleDeleteConversation}
          onSelectConversation={selectConversation}
          onSendMessage={handleSendMessage}
        />
      )}
    </div>
  );
}
