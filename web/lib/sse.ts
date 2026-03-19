import { DashboardSnapshot } from "@/types/dashboard";

interface StreamHandlers {
  onSnapshot: (snapshot: DashboardSnapshot) => void;
  onError: (error: string) => void;
}

export function openSnapshotStream(
  apiBase: string,
  handlers: StreamHandlers
): EventSource {
  const stream = new EventSource(`${apiBase}/api/stream`);
  stream.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as DashboardSnapshot;
      handlers.onSnapshot(data);
    } catch (error) {
      handlers.onError(`Failed to parse stream event: ${String(error)}`);
    }
  };
  stream.onerror = () => {
    handlers.onError("Stream disconnected. Retrying...");
  };
  return stream;
}
