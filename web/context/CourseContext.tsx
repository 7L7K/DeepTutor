"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { fetchAuthStatus } from "@/lib/auth";
import {
  archiveCourse as archiveCourseApi,
  createCourse as createCourseApi,
  getOrCreateGeneralStudy,
  listCourses,
  restoreCourse as restoreCourseApi,
  type Course,
} from "@/lib/course-api";
import {
  courseSelectionStorageKey,
  getRuntimeActiveCourseId,
  isCurrentCourseRequest,
  setRuntimeActiveCourseId,
  shouldClearArchivedCourseSelection,
  validatedActiveCourseId,
} from "@/lib/course-selection";

interface CourseContextValue {
  identity: string | null;
  courses: Course[];
  activeCourse: Course | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createCourse: (title: string) => Promise<Course>;
  openGeneralStudy: () => Promise<Course>;
  selectCourse: (courseId: string | null) => void;
  archiveCourse: (course: Course) => Promise<void>;
  restoreCourse: (course: Course) => Promise<void>;
}

const CourseContext = createContext<CourseContextValue | null>(null);

export function CourseProvider({ children }: { children: React.ReactNode }) {
  const [identity, setIdentity] = useState<string | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const identityRef = useRef<string | null>(null);
  const requestEpochRef = useRef(0);

  const resolveIdentity = useCallback(async () => {
    const status = await fetchAuthStatus();
    const next = status?.authenticated ? status.user_id || null : null;
    const previous = identityRef.current;
    if (previous !== next) {
      requestEpochRef.current += 1;
      identityRef.current = next;
      if (previous) {
        window.localStorage.removeItem(courseSelectionStorageKey(previous));
      }
      setRuntimeActiveCourseId(null);
      setActiveCourseId(null);
      setCourses([]);
    }
    setIdentity(next);
    return next;
  }, []);

  const loadForIdentity = useCallback(async (userId: string) => {
    const requestEpoch = ++requestEpochRef.current;
    const next = await listCourses();
    if (
      !isCurrentCourseRequest(
        requestEpoch,
        requestEpochRef.current,
        userId,
        identityRef.current,
      )
    ) {
      return;
    }
    setCourses(next);
    const key = courseSelectionStorageKey(userId);
    const stored = window.localStorage.getItem(key);
    const valid = validatedActiveCourseId(next, stored);
    setRuntimeActiveCourseId(valid);
    setActiveCourseId(valid);
    if (!valid) window.localStorage.removeItem(key);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Keep the initial load callback stable after auth identity resolves.
      // Depending on the state value here recreates `refresh`, retriggers the
      // mount effect, and sends a duplicate owner-scoped Course summary query.
      const userId = identityRef.current || (await resolveIdentity());
      if (!userId) return;
      await loadForIdentity(userId);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not load courses",
      );
    } finally {
      setLoading(false);
    }
  }, [loadForIdentity, resolveIdentity]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onAuthChanged = () => {
      setLoading(true);
      void resolveIdentity()
        .then(async (userId) => {
          if (userId) await loadForIdentity(userId);
        })
        .finally(() => setLoading(false));
    };
    window.addEventListener("dt:auth-changed", onAuthChanged);
    return () => {
      window.removeEventListener("dt:auth-changed", onAuthChanged);
    };
  }, [identity, loadForIdentity, resolveIdentity]);

  const selectCourse = useCallback(
    (courseId: string | null) => {
      const valid = validatedActiveCourseId(courses, courseId);
      setRuntimeActiveCourseId(valid);
      setActiveCourseId(valid);
      if (identity) {
        const key = courseSelectionStorageKey(identity);
        if (valid) window.localStorage.setItem(key, valid);
        else window.localStorage.removeItem(key);
      }
    },
    [courses, identity],
  );

  const createCourse = useCallback(
    async (title: string) => {
      const requestedIdentity = identityRef.current || (await resolveIdentity());
      if (!requestedIdentity) {
        throw new Error("Sign in before creating a Course");
      }
      const created = await createCourseApi(title);
      const responseEpoch = ++requestEpochRef.current;
      if (
        !isCurrentCourseRequest(
          responseEpoch,
          requestEpochRef.current,
          requestedIdentity,
          identityRef.current,
        )
      ) {
        throw new Error("Authentication changed while creating the Course");
      }
      setCourses((previous) => [created, ...previous]);
      setRuntimeActiveCourseId(created.id);
      setActiveCourseId(created.id);
      if (requestedIdentity) {
        window.localStorage.setItem(
          courseSelectionStorageKey(requestedIdentity),
          created.id,
        );
      }
      return created;
    },
    [resolveIdentity],
  );

  const openGeneralStudy = useCallback(async () => {
    const requestedIdentity = identityRef.current || (await resolveIdentity());
    if (!requestedIdentity) {
      throw new Error("Sign in before opening General Study");
    }
    const general = await getOrCreateGeneralStudy();
    const responseEpoch = ++requestEpochRef.current;
    if (
      !isCurrentCourseRequest(
        responseEpoch,
        requestEpochRef.current,
        requestedIdentity,
        identityRef.current,
      )
    ) {
      throw new Error("Authentication changed while opening General Study");
    }
    setCourses((previous) => [
      general,
      ...previous.filter((course) => course.id !== general.id),
    ]);
    setRuntimeActiveCourseId(general.id);
    setActiveCourseId(general.id);
    window.localStorage.setItem(
      courseSelectionStorageKey(requestedIdentity),
      general.id,
    );
    return general;
  }, [resolveIdentity]);

  const archiveCourse = useCallback(
    async (course: Course) => {
      const requestedIdentity = identityRef.current;
      if (!requestedIdentity) {
        throw new Error("Sign in before archiving a Course");
      }
      const updated = await archiveCourseApi(course);
      const responseEpoch = ++requestEpochRef.current;
      if (
        !isCurrentCourseRequest(
          responseEpoch,
          requestEpochRef.current,
          requestedIdentity,
          identityRef.current,
        )
      ) {
        throw new Error("Authentication changed while archiving the Course");
      }
      setCourses((previous) =>
        previous.map((item) => (item.id === updated.id ? updated : item)),
      );
      if (
        shouldClearArchivedCourseSelection(
          getRuntimeActiveCourseId(),
          updated.id,
        )
      ) {
        selectCourse(null);
      }
    },
    [selectCourse],
  );

  const restoreCourse = useCallback(async (course: Course) => {
    const requestedIdentity = identityRef.current;
    if (!requestedIdentity) {
      throw new Error("Sign in before restoring a Course");
    }
    const updated = await restoreCourseApi(course);
    const responseEpoch = ++requestEpochRef.current;
    if (
      !isCurrentCourseRequest(
        responseEpoch,
        requestEpochRef.current,
        requestedIdentity,
        identityRef.current,
      )
    ) {
      throw new Error("Authentication changed while restoring the Course");
    }
    setCourses((previous) =>
      previous.map((item) => (item.id === updated.id ? updated : item)),
    );
  }, []);

  const value = useMemo<CourseContextValue>(
    () => ({
      identity,
      courses,
      activeCourse:
        courses.find((course) => course.id === activeCourseId) || null,
      loading,
      error,
      refresh,
      createCourse,
      openGeneralStudy,
      selectCourse,
      archiveCourse,
      restoreCourse,
    }),
    [
      courses,
      identity,
      activeCourseId,
      loading,
      error,
      refresh,
      createCourse,
      openGeneralStudy,
      selectCourse,
      archiveCourse,
      restoreCourse,
    ],
  );

  return (
    <CourseContext.Provider value={value}>{children}</CourseContext.Provider>
  );
}

export function useCourses() {
  const context = useContext(CourseContext);
  if (!context)
    throw new Error("useCourses must be used inside CourseProvider");
  return context;
}
