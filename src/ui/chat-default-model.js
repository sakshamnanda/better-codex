// Initialize each new chat once; later user choices and existing chats keep their model.
function gatewayChatDefaultModel(React, conversationId, ready, selectDefault) {
  const initialized = React.useRef(false);
  React.useEffect(() => {
    if (conversationId != null) {
      initialized.current = false;
      return;
    }
    if (!ready || initialized.current) return;
    initialized.current = true;
    selectDefault();
  }, [conversationId, ready, selectDefault]);
}
