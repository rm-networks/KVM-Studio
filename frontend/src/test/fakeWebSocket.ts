// In-memory WebSocket for tests: records instances so a test can push messages.
export class FakeWebSocket extends EventTarget {
  static instances: FakeWebSocket[] = [];
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  readonly url: string;
  readonly protocols: string[];

  constructor(url: string, protocols: string | string[] = []) {
    super();
    this.url = url;
    this.protocols = typeof protocols === "string" ? [protocols] : protocols;
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.onopen?.(new Event("open"));
  }

  push(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }

  close() {
    this.onclose?.(new CloseEvent("close"));
  }

  send() {}
}
