const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SSEHandler = (event: { type: string; data: Record<string, unknown> }) => void;

export function subscribeToEvents(onEvent: SSEHandler): () => void {
  let source: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  function connect() {
    if (closed) return;
    source = new EventSource(`${API_URL}/events`);

    source.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data);
        onEvent(event);
      } catch {
        // ignore malformed events
      }
    };

    source.onerror = () => {
      source?.close();
      if (!closed) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };
  }

  connect();

  return () => {
    closed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    source?.close();
  };
}
