import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import "../i18n";
import { FakeWebSocket } from "./fakeWebSocket";

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
