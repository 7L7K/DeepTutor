/**
 * Reconcile optimistic (negative, client-generated) message ids with the
 * persisted ids the backend attaches to a turn's ``done`` event.
 *
 * Historically the chat context refetched the whole session after every turn
 * just to learn two ids — an O(conversation length) network + normalize +
 * re-render pass that froze the UI for seconds on long chats. This module is
 * the replacement: a targeted, pure, in-place id swap.
 *
 * Ids are typed ``number`` to match ``MessageItem``, but PocketBase-backed
 * deployments deliver string record ids at runtime (the long-standing
 * convention across ``hydrateMessages`` and the session API). All comparisons
 * here are identity-based, so both shapes flow through unchanged; only the
 * "is optimistic" check (`typeof id === "number" && id < 0`) is type-aware.
 */

export interface ReconcilableMessage {
  id?: number;
  role: "user" | "assistant" | "system";
  content?: string;
  parentMessageId?: number | null;
  events?: Array<{ turn_id?: string }>;
}

export interface TurnPersistedIds {
  /** Turn the ids belong to — used to locate the right assistant bubble. */
  turnId?: string | null;
  /** Persisted id of the user row, absent on regenerate turns. */
  userMessageId?: number | null;
  /** Persisted id of the assistant row. */
  assistantMessageId?: number | null;
}

export interface ReconcileResult<T> {
  messages: T[];
  selectedBranches: Record<string, number>;
  changed: boolean;
}

export function latestAssistantMatchesTurn(
  messages: ReconcilableMessage[],
  turnId?: string | null,
  assistantMessageId?: number | null,
): boolean {
  if (messages[messages.length - 1]?.role !== "assistant") return false;
  if (!turnId && assistantMessageId == null) return true;
  const assistant = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  if (!assistant) return false;
  const eventTurnIds = (assistant.events ?? [])
    .map((event) => event.turn_id)
    .filter((eventTurnId): eventTurnId is string => Boolean(eventTurnId));
  if (
    assistantMessageId != null &&
    assistant.id !== assistantMessageId &&
    !(isOptimisticId(assistant.id) &&
      !(assistant.content ?? "").trim() &&
      (!turnId || eventTurnIds.length === 0 || eventTurnIds.includes(turnId)))
  ) {
    return false;
  }
  // A lost stream can leave the placeholder with no event metadata at all.
  // In that case the assistant row position (and, when available, persisted
  // id) is the only local evidence we have, so let the server snapshot fill it.
  return !turnId || eventTurnIds.length === 0 || eventTurnIds.includes(turnId);
}

/**
 * A revalidation may accept a metadata-free optimistic placeholder only when
 * the provider has recorded the same turn as its most recent completion.
 * Without this second identity, an older no-event response could replace a
 * newer blank turn because both look locally identical.
 */
export function canApplyTurnRevalidation(
  messages: ReconcilableMessage[],
  expectedTurnId?: string | null,
  expectedAssistantMessageId?: number | null,
  lastCompletedTurnId?: string | null,
  lastCompletedAssistantMessageId?: number | null,
): boolean {
  if (expectedTurnId && lastCompletedTurnId !== expectedTurnId) return false;
  if (
    expectedAssistantMessageId != null &&
    lastCompletedAssistantMessageId !== expectedAssistantMessageId
  ) {
    return false;
  }
  return latestAssistantMatchesTurn(messages, expectedTurnId, expectedAssistantMessageId);
}

/** Verify that a fetched snapshot contains the identity the refresh was for. */
export function snapshotMatchesExpectedTurn(
  messages: ReconcilableMessage[],
  expectedTurnId?: string | null,
  expectedAssistantMessageId?: number | null,
): boolean {
  if (!expectedTurnId && expectedAssistantMessageId == null) return true;
  const assistant = messages[messages.length - 1];
  if (!assistant || assistant.role !== "assistant") return false;
  if (expectedAssistantMessageId != null) return assistant.id === expectedAssistantMessageId;
  return (assistant.events ?? []).some((event) => event.turn_id === expectedTurnId);
}

/**
 * The completed-turn event carries persisted row ids, but the assistant body
 * still arrives through the live event stream. If that stream was interrupted
 * or a client/backend version mismatch filtered the content event, the local
 * assistant row can be empty even though the server has persisted the answer.
 */
export function latestAssistantNeedsHydration(
  messages: ReconcilableMessage[],
  turnId?: string | null,
  assistantMessageId?: number | null,
): boolean {
  const assistant = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  if (!assistant || !latestAssistantMatchesTurn(messages, turnId, assistantMessageId)) {
    return false;
  }
  return !(assistant.content ?? "").trim();
}

function isOptimisticId(id: unknown): id is number {
  return typeof id === "number" && id < 0;
}

/**
 * Swap the turn's optimistic message ids for their persisted counterparts.
 *
 * Locates the turn's assistant bubble (last assistant message carrying an
 * event with ``turnId``) and the user message immediately preceding it. A
 * persisted assistant id without a turn id is intentionally not reconciled
 * by position; the caller must use the guarded session snapshot instead.
 * Only optimistic (negative) ids are ever overwritten — rows that already
 * carry persisted ids (e.g. after a mid-turn session reload) are left
 * untouched, which also makes stale ``done`` replays harmless. All
 * ``parentMessageId`` pointers and ``selectedBranches`` entries referencing
 * a swapped id are remapped alongside it.
 *
 * Returns ``changed: false`` (with the original references) when there is
 * nothing to do, so the reducer can bail without a state update.
 */
export function reconcileTurnIds<T extends ReconcilableMessage>(
  messages: T[],
  selectedBranches: Record<string, number>,
  ids: TurnPersistedIds,
): ReconcileResult<T> {
  const unchanged: ReconcileResult<T> = {
    messages,
    selectedBranches,
    changed: false,
  };
  if (ids.assistantMessageId == null && ids.userMessageId == null) {
    return unchanged;
  }
  // Without a turn id there is no safe way to tell which optimistic assistant
  // a persisted assistant id belongs to. The caller must use a guarded
  // session snapshot instead of renaming the latest bubble by position.
  if (!ids.turnId) return unchanged;

  let assistantIndex = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== "assistant") continue;
    if (ids.turnId) {
      const events = message.events;
      if (
        !Array.isArray(events) ||
        !events.some((event) => event?.turn_id === ids.turnId)
      ) {
        continue;
      }
    }
    assistantIndex = i;
    break;
  }
  if (assistantIndex === -1) return unchanged;

  // Old optimistic id → persisted id, applied to ids and parent pointers.
  const remap = new Map<number, number>();
  const assistant = messages[assistantIndex];
  if (ids.assistantMessageId != null && isOptimisticId(assistant.id)) {
    remap.set(assistant.id, ids.assistantMessageId);
  }
  if (ids.userMessageId != null) {
    for (let i = assistantIndex - 1; i >= 0; i--) {
      const message = messages[i];
      if (message.role !== "user") continue;
      if (isOptimisticId(message.id)) {
        remap.set(message.id, ids.userMessageId);
      }
      break;
    }
  }
  if (remap.size === 0) return unchanged;

  const nextMessages = messages.map((message) => {
    const nextId = message.id !== undefined ? remap.get(message.id) : undefined;
    const nextParent =
      message.parentMessageId != null
        ? remap.get(message.parentMessageId)
        : undefined;
    if (nextId === undefined && nextParent === undefined) return message;
    return {
      ...message,
      ...(nextId !== undefined ? { id: nextId } : {}),
      ...(nextParent !== undefined ? { parentMessageId: nextParent } : {}),
    };
  });

  let nextBranches = selectedBranches;
  const branchEntries = Object.entries(selectedBranches);
  if (branchEntries.length > 0) {
    let branchesChanged = false;
    const rebuilt: Record<string, number> = {};
    for (const [parentKey, childId] of branchEntries) {
      const parentAsNumber = Number(parentKey);
      const remappedParent = Number.isNaN(parentAsNumber)
        ? undefined
        : remap.get(parentAsNumber);
      const remappedChild = remap.get(childId);
      rebuilt[
        remappedParent !== undefined ? String(remappedParent) : parentKey
      ] = remappedChild !== undefined ? remappedChild : childId;
      if (remappedParent !== undefined || remappedChild !== undefined) {
        branchesChanged = true;
      }
    }
    if (branchesChanged) nextBranches = rebuilt;
  }

  return {
    messages: nextMessages,
    selectedBranches: nextBranches,
    changed: true,
  };
}
