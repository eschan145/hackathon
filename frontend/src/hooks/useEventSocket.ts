import { useEffect, useRef } from "react";
import { AssistantEvent, AssistantEventType, BACKEND_WS_URL } from "../api/client";

type Listener = (event: AssistantEvent) => void;

/**
 * Singleton-ish WebSocket manager so multiple components/pages can each
 * call useEventSocket() without opening duplicate sockets. Auto-reconnects
 * with backoff. Exposes a subscribe-by-type API.
 */
class EventSocketManager {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private wildcardListeners = new Set<Listener>();
  private reconnectDelay = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connectionListeners = new Set<(connected: boolean) => void>();
  private closedByUser = false;

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.closedByUser = false;
    try {
      this.ws = new WebSocket(BACKEND_WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.connectionListeners.forEach((cb) => cb(true));
    };

    this.ws.onmessage = (msg) => {
      let event: AssistantEvent | null = null;
      try {
        event = JSON.parse(msg.data);
      } catch {
        return;
      }
      if (!event) return;
      this.wildcardListeners.forEach((cb) => cb(event as AssistantEvent));
      const typed = this.listeners.get(event.type);
      typed?.forEach((cb) => cb(event as AssistantEvent));
    };

    this.ws.onclose = () => {
      this.connectionListeners.forEach((cb) => cb(false));
      if (!this.closedByUser) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 15000);
      this.connect();
    }, this.reconnectDelay);
  }

  subscribe(type: AssistantEventType | "*", cb: Listener): () => void {
    if (type === "*") {
      this.wildcardListeners.add(cb);
      return () => this.wildcardListeners.delete(cb);
    }
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(cb);
    return () => this.listeners.get(type)?.delete(cb);
  }

  onConnectionChange(cb: (connected: boolean) => void): () => void {
    this.connectionListeners.add(cb);
    return () => this.connectionListeners.delete(cb);
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

export const eventSocket = new EventSocketManager();

export interface UseEventSocketApi {
  subscribe: (type: AssistantEventType | "*", cb: Listener) => () => void;
  isConnected: boolean;
}

/** React hook wrapping the shared event socket connection. */
export function useEventSocket(): UseEventSocketApi {
  const connectedRef = useRef(eventSocket.isConnected);

  useEffect(() => {
    eventSocket.connect();
  }, []);

  return {
    subscribe: eventSocket.subscribe.bind(eventSocket),
    isConnected: connectedRef.current,
  };
}
