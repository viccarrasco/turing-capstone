function onListItemKeyDown(event, onSelect) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onSelect();
  }
}

export default function ConversationsView({
  conversations,
  activeConversation,
  loadingConversation,
  messageError,
  messageText,
  setMessageText,
  onCreateConversation,
  onDeleteConversation,
  onSelectConversation,
  onSendMessage
}) {
  return (
    <section className="panel conversations">
      <div className="sidebar">
        <div className="sidebar__header">
          <h2>Conversations</h2>
          <button className="secondary" onClick={onCreateConversation}>
            New
          </button>
        </div>
        <div className="list">
          {conversations.length === 0 ? (
            <div className="empty-state">
              <p>No conversations yet.</p>
              <span className="muted">Create a new thread to begin.</span>
            </div>
          ) : (
            conversations.map((conv) => {
              const isActive = activeConversation?.conversation?.id === conv.id;
              return (
                <div
                  key={conv.id}
                  role="button"
                  tabIndex={0}
                  className={isActive ? "list-item list-item--active" : "list-item"}
                  onClick={() => onSelectConversation(conv.id)}
                  onKeyDown={(event) => onListItemKeyDown(event, () => onSelectConversation(conv.id))}
                >
                  <div>
                    <strong>{conv.title || `Conversation ${conv.id}`}</strong>
                    <small>Updated {new Date(conv.updated_at).toLocaleString()}</small>
                  </div>
                  <button
                    type="button"
                    className="delete"
                    onClick={(event) => {
                      event.stopPropagation();
                      onDeleteConversation(conv.id);
                    }}
                  >
                    Delete
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      <div className="conversation-panel">
        {loadingConversation && <p>Loading...</p>}
        {messageError && <p className="error">{messageError}</p>}
        {activeConversation ? (
          <>
            <div className="thread">
              {activeConversation.messages.map((msg) => (
                <div key={msg.id} className={`bubble bubble--${msg.role}`}>
                  <div className="bubble__meta">
                    <span className="pill">{msg.role}</span>
                    {msg.created_at && <span className="muted">{new Date(msg.created_at).toLocaleString()}</span>}
                  </div>
                  <p>{msg.content}</p>
                  {msg.sql_query && (
                    <details>
                      <summary>SQL</summary>
                      <pre>{msg.sql_query}</pre>
                    </details>
                  )}
                  {msg.query_results && msg.query_results.length > 0 && (
                    <details>
                      <summary>Results</summary>
                      <pre>{JSON.stringify(msg.query_results, null, 2)}</pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
            <form className="composer" onSubmit={onSendMessage}>
              <textarea
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                placeholder="Ask something about this company..."
                rows={3}
              />
              <button className="primary" disabled={loadingConversation || !messageText.trim()}>
                Send
              </button>
            </form>
          </>
        ) : (
          <div className="empty-state">
            <p>Select a conversation or create a new one.</p>
            <span className="muted">Threads keep SQL + results attached to the dialog.</span>
          </div>
        )}
      </div>
    </section>
  );
}
