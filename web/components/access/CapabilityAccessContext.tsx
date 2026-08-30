"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { Capability } from "@/lib/capability-routes";
import { apiFetch, apiUrl } from "@/lib/api";
import { listLLMOptions } from "@/lib/llm-options";

type CapabilityAccessValue = {
  /** Whether at least one access probe has completed successfully. */
  known: boolean;
  /** True while access is being established for the first time. */
  loading: boolean;
  /** True while confirmed access is being rechecked in the background. */
  refreshing: boolean;
  /** Admins manage the catalog directly and are never gated. */
  isAdmin: boolean;
  /** Whether the current user has at least one usable LLM model. */
  hasLlm: boolean;
  /** Learner-safe failure from the latest access probe, if it could not complete. */
  error: string | null;
  /** Whether the current user may use a gated capability. */
  has: (capability: Capability) => boolean;
  /** Re-probe access (used on tab focus to pick up mid-session grant changes). */
  refresh: () => Promise<void>;
};

// Fail closed outside a provider as well. Every learner-facing tree installs
// CapabilityAccessProvider; an accidental missing provider must not make
// deployment capabilities appear available.
const DEFAULT_VALUE: CapabilityAccessValue = {
  known: false,
  loading: true,
  refreshing: false,
  isAdmin: false,
  hasLlm: false,
  error: null,
  has: () => false,
  refresh: async () => {},
};

const CapabilityAccessContext =
  createContext<CapabilityAccessValue>(DEFAULT_VALUE);

export function useCapabilityAccess(): CapabilityAccessValue {
  return useContext(CapabilityAccessContext);
}

export function CapabilityAccessProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [isAdmin, setIsAdmin] = useState(false);
  const [hasLlm, setHasLlm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [known, setKnown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const requestEpochRef = useRef(0);
  const knownRef = useRef(false);

  const refresh = useCallback(async () => {
    const requestEpoch = ++requestEpochRef.current;
    const isBackgroundRefresh = knownRef.current;
    if (isBackgroundRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      // The settings payload only exposes the catalog to admins, so its
      // presence is our admin signal — admins are never gated.
      const res = await apiFetch(apiUrl("/api/v1/settings"));
      if (!res.ok) throw new Error("Access probe failed");
      const payload = (await res.json()) as { catalog?: unknown };
      if (requestEpoch !== requestEpochRef.current) return;
      if (payload.catalog) {
        setIsAdmin(true);
        setHasLlm(true);
      } else {
        // Non-admins: their grant-filtered LLM options decide access.
        const { options } = await listLLMOptions({ force: true });
        if (requestEpoch !== requestEpochRef.current) return;
        setIsAdmin(false);
        setHasLlm(options.length > 0);
      }
      knownRef.current = true;
      setKnown(true);
    } catch {
      if (requestEpoch !== requestEpochRef.current) return;
      setError("Could not verify feature access. Try again.");
    } finally {
      if (requestEpoch === requestEpochRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-check when the user returns to the tab. This is what surfaces a
  // mid-session revocation (admin removed the grant while the tab was open)
  // without any polling — the next focus re-reads access and locks the UI.
  useEffect(() => {
    const onFocus = () => void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const has = useCallback(
    (_capability: Capability): boolean => {
      // Only LLM is gated today. Fail closed until one probe succeeds, then
      // preserve that confirmed decision while a background probe is pending
      // or fails. A later successful probe may still revoke the grant.
      if (!known) return false;
      if (isAdmin) return true;
      return hasLlm;
    },
    [isAdmin, known, hasLlm],
  );

  return (
    <CapabilityAccessContext.Provider
      value={{ known, loading, refreshing, isAdmin, hasLlm, error, has, refresh }}
    >
      {children}
    </CapabilityAccessContext.Provider>
  );
}
