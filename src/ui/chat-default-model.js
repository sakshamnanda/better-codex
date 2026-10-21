// Initialize each new chat once; later user choices and existing chats keep their model.
function gatewayChatDefaultModel(React, conversationId, ready, selectDefault, contextKey = ``) {
  const initialized = React.useRef(null);
  React.useEffect(() => {
    if (conversationId != null) {
      initialized.current = null;
      return;
    }
    if (!ready || initialized.current === contextKey) return;
    initialized.current = contextKey;
    selectDefault();
  }, [conversationId, ready, selectDefault, contextKey]);
}
