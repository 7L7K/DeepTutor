"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  resolveBlueWayLaunch,
  type BlueWayLaunchResult,
  type BlueWayLaunchStatus,
} from "@/lib/blueway-launch-api";

const ERROR_COPY: Record<Exclude<BlueWayLaunchStatus, "ready" | "stale" | "login_required">, string> = {
  course_not_ready: "This Course is not ready to open yet.",
  connection_revoked: "The BlueWay connection for this Course is no longer active.",
  course_not_found: "This Course is not available to this account.",
  term_mismatch: "This Course link does not match the requested academic term.",
  temporarily_unavailable: "TEEECHR could not verify this Course right now. Try again.",
};

type BlueWayLaunchValue = BlueWayLaunchResult | {
  schema_version: "teeechr.blueway.launch.v1";
  status: "login_required";
};

export default function BlueWayLaunch() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const externalCourseId = searchParams.get("external_course_id")?.trim() ?? "";
  const externalTermId = searchParams.get("external_term_id")?.trim() ?? "";
  const requestKey = `${externalCourseId}\u0000${externalTermId}`;
  const [resolved, setResolved] = useState<{ key: string; value: BlueWayLaunchValue } | null>(null);
  const hasLaunchIdentity = Boolean(externalCourseId && externalTermId);

  useEffect(() => {
    let cancelled = false;
    if (!hasLaunchIdentity) return () => {
      cancelled = true;
    };
    void resolveBlueWayLaunch({ externalCourseId, externalTermId }).then((next) => {
      if (!cancelled) setResolved({ key: requestKey, value: next });
    });
    return () => {
      cancelled = true;
    };
  }, [externalCourseId, externalTermId, hasLaunchIdentity, requestKey]);

  const result = useMemo<BlueWayLaunchValue | null>(
    () => !hasLaunchIdentity
      ? { schema_version: "teeechr.blueway.launch.v1", status: "term_mismatch" }
      : resolved?.key === requestKey
        ? resolved.value
        : null,
    [hasLaunchIdentity, requestKey, resolved],
  );

  useEffect(() => {
    if (!result) return;
    if (result.status === "login_required") {
      const next = `${window.location.pathname}${window.location.search}`;
      router.replace(`/login?next=${encodeURIComponent(next)}`);
      return;
    }
    if ((result.status === "ready" || result.status === "stale") && result.course_id) {
      router.replace(`/classes/${encodeURIComponent(result.course_id)}`);
    }
  }, [result, router]);

  const status = result?.status;
  const message = status && status !== "ready" && status !== "stale" && status !== "login_required"
    ? ERROR_COPY[status]
    : null;

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <section className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--card)] p-7 shadow-sm">
        <p className="text-sm font-medium text-[var(--muted-foreground)]">TEEECHR</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--foreground)]">
          {message ? "Course link unavailable" : "Opening your Course"}
        </h1>
        {message ? (
          <p role="alert" data-testid={`blueway-launch-status-${status}`} className="mt-4 text-sm leading-6 text-[var(--muted-foreground)]">
            {message}
          </p>
        ) : (
          <p role="status" data-testid="blueway-launch-resolving" className="mt-4 text-sm leading-6 text-[var(--muted-foreground)]">
            Verifying the exact Course and academic term in your private workspace…
          </p>
        )}
        {message ? (
          <Link
            href="/classes"
            className="mt-6 inline-flex rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            Go to Classes
          </Link>
        ) : null}
      </section>
    </main>
  );
}
