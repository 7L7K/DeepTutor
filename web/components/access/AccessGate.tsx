"use client";

import { useEffect, useState, type ReactNode } from "react";
import { claimAccessCode, getCurrentTester, type CurrentTester } from "@/lib/access-api";

export function AccessGate({ children }: { children: ReactNode }) {
  const enabled = process.env.NEXT_PUBLIC_PRIVATE_TESTER_GATE === "true";
  const [tester, setTester] = useState<CurrentTester | null>(null);
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "signed-out">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getCurrentTester()
      .then((current) => {
        if (cancelled) return;
        setTester(current);
        setStatus(current ? "ready" : "signed-out");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("signed-out");
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) return;
    setError("");
    setStatus("loading");
    try {
      const nextTester = await claimAccessCode(trimmed);
      setTester(nextTester);
      setStatus("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid access code");
      setStatus("signed-out");
    }
  };

  if (status === "ready" && tester) {
    return <>{children}</>;
  }

  if (!enabled) {
    return <>{children}</>;
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_20%,rgba(26,115,232,0.12),transparent_28%),linear-gradient(135deg,var(--background),var(--secondary))] px-4 py-10 text-[var(--foreground)]">
      <div className="mx-auto flex min-h-[80vh] max-w-md flex-col justify-center">
        <section className="rounded-[28px] border border-[var(--border)] bg-[var(--card)]/92 p-7 shadow-[0_24px_80px_rgba(15,23,42,0.14)]">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.24em] text-[var(--muted-foreground)]">
            Private tester access
          </p>
          <h1 className="mb-3 text-3xl font-semibold tracking-[-0.04em]">
            Enter your code to open DeepTutor.
          </h1>
          <p className="mb-6 text-sm leading-6 text-[var(--muted-foreground)]">
            Each code keeps chat, practice, flashcards, and knowledge work separated for that tester.
          </p>
          <form onSubmit={submit} className="space-y-3">
            <label className="block text-sm font-medium" htmlFor="access-code">
              Access code
            </label>
            <input
              id="access-code"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="Enter tester code"
              className="w-full rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-base outline-none transition focus:border-[var(--accent)]"
              autoComplete="one-time-code"
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={status === "loading"}
              className="w-full rounded-2xl bg-[var(--foreground)] px-4 py-3 text-sm font-semibold text-[var(--background)] transition hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
            >
              {status === "loading" ? "Checking..." : "Continue"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
