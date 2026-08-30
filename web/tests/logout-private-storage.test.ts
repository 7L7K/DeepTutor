import test from "node:test";
import assert from "node:assert/strict";

import { clearPrivateBrowserStateOnLogout } from "../lib/auth";

test("successful logout cleanup removes private capability state only", () => {
  const previousWindow = global.window;
  const values = new Map<string, string>([
    ["dt:chat:capability-config:session-a", "private-a"],
    ["dt:chat:capability-config:session-b", "private-b"],
    ["dt:chat:viewer-panel", "1"],
    ["unrelated", "keep"],
  ]);
  const localStorage = {
    get length() {
      return values.size;
    },
    key(index: number) {
      return Array.from(values.keys())[index] ?? null;
    },
    removeItem(key: string) {
      values.delete(key);
    },
  };
  global.window = { localStorage } as unknown as Window & typeof globalThis;

  try {
    clearPrivateBrowserStateOnLogout();
  } finally {
    global.window = previousWindow;
  }

  assert.deepEqual(Array.from(values.entries()), [
    ["dt:chat:viewer-panel", "1"],
    ["unrelated", "keep"],
  ]);
});
