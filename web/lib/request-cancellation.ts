/**
 * A delayed read may update UI only while its route generation is still the
 * active one and navigation has not cancelled its transport.
 */
export function isCurrentAbortableRequest(
  requestEpoch: number,
  currentEpoch: number,
  signal: AbortSignal,
): boolean {
  return requestEpoch === currentEpoch && !signal.aborted;
}

/** A navigation-aborted snapshot must never select shared application state. */
export function canApplySessionLoad(signal?: AbortSignal): boolean {
  return !signal?.aborted;
}
