/**
 * Model capability a feature depends on. As of the multi-user release, the only
 * per-user-grantable model capability is the LLM — embedding/search are shared
 * admin infrastructure and are never gated per user.
 */
export type Capability = "llm";

/**
 * Workspace surfaces that are intentionally reserved for administrators in
 * the beta. User-scoped chat access remains available through the regular
 * composer and assigned Partners flows; this list protects the full
 * management workspaces and their direct URLs.
 */
export const ADMIN_ONLY_ROUTE_PREFIXES: ReadonlyArray<string> = [
  "/agents",
  "/book",
  "/co-writer",
  "/knowledge",
  "/memory",
  "/playground",
  "/space/cli-apps",
];

export function adminOnlyForPath(pathname: string): boolean {
  return ADMIN_ONLY_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Single source of truth mapping a workspace feature route to the model
 * capability it needs in order to function. Features absent from this list
 * require no per-user model and are always available (Knowledge, Space,
 * Memory, Notebook, Settings, …).
 *
 * Both the sidebar (to lock nav items) and the route-level CapabilityGate
 * (to lock the page itself) read from here, so a new gated feature only has
 * to be declared once.
 */
export const ROUTE_CAPABILITIES: ReadonlyArray<{
  prefix: string;
  capability: Capability;
}> = [
  { prefix: "/partners", capability: "llm" },
  { prefix: "/co-writer", capability: "llm" },
  { prefix: "/book", capability: "llm" },
  { prefix: "/playground", capability: "llm" },
];

/**
 * Returns the capability required for a pathname, or null if none is needed.
 * Matches on a path-segment boundary (exact, or prefix followed by "/") so a
 * sibling route like "/booket" can never be swallowed by the "/book" prefix.
 */
export function capabilityForPath(pathname: string): Capability | null {
  const match = ROUTE_CAPABILITIES.find(
    (r) => pathname === r.prefix || pathname.startsWith(`${r.prefix}/`),
  );
  return match ? match.capability : null;
}

/**
 * Human-facing phrase for a capability, used in the "ask your admin" copy.
 * Kept as plain English keys so react-i18next can translate them later.
 */
export const CAPABILITY_LABEL: Record<Capability, string> = {
  llm: "an LLM model",
};
