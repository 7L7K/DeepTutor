/**
 * A delayed read may update UI only while its route generation is still the
 * active one. A caller may additionally cancel its transport, but ordinary
 * route changes use the epoch alone so React development effect replays do
 * not turn successful reads into browser-level request failures.
 */
export function isCurrentAbortableRequest(
  requestEpoch: number,
  currentEpoch: number,
  signal?: AbortSignal,
): boolean {
  return requestEpoch === currentEpoch && !signal?.aborted;
}

/** A cancelled or superseded snapshot must never select shared application state. */
export function canApplySessionLoad(
  signal?: AbortSignal,
  isCurrent: () => boolean = () => true,
): boolean {
  return !signal?.aborted && isCurrent();
}
