import test from "node:test";
import assert from "node:assert/strict";

import { UnifiedWSClient } from "../lib/unified-ws";

class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((error: unknown) => void) | null = null;

  constructor(public readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(payload: string): void {
    this.sent.push(payload);
  }

  close(): void {
    this.readyState = 3;
  }
}

test("reconnect and control messages use explicit session-bound course identity", () => {
  const original = globalThis.WebSocket;
  FakeWebSocket.instances = [];
  globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  try {
    const client = new UnifiedWSClient(() => undefined);
    client.setResumeState("turn_a", 7, "crs_a");
    client.connect();
    const socket = FakeWebSocket.instances[0];
    socket.onopen?.();

    assert.deepEqual(JSON.parse(socket.sent[0]), {
      type: "resume_from",
      turn_id: "turn_a",
      seq: 7,
      course_id: "crs_a",
    });

    client.send({ type: "cancel_turn", turn_id: "turn_a", course_id: "crs_a" });
    assert.equal(JSON.parse(socket.sent[1]).course_id, "crs_a");

    client.send({ type: "cancel_turn", turn_id: "generic_turn" });
    assert.equal("course_id" in JSON.parse(socket.sent[2]), false);
    client.disconnect();
  } finally {
    globalThis.WebSocket = original;
  }
});
