import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import i18n from "../i18n";
import { FakeWebSocket } from "./fakeWebSocket";

// The component tests read the French text: they cover the translation too.
await i18n.changeLanguage("fr");

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});
