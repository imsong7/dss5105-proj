import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { Job } from "../domain/email";
import { fetchSavedJobs, removeSavedJob, saveJob } from "../services/flask";

interface SavedJobs {
  jobs: readonly Job[];
  isSaved: (id: string) => boolean;
  /** Save the job, or remove it when it is already saved. */
  toggle: (job: Job) => Promise<void>;
  remove: (id: string) => Promise<void>;
  error: string | null;
}

const SavedJobsContext = createContext<SavedJobs | null>(null);

/** The account's saved jobs, shared by the email view and Today. */
export function SavedJobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<readonly Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    fetchSavedJobs(abort.signal)
      .then(setJobs)
      .catch(() => {
        // No saved jobs yet, or an older server: the list just stays empty.
      });
    return () => abort.abort();
  }, []);

  const remove = useCallback(async (id: string) => {
    setError(null);
    const before = jobs;
    setJobs((current) => current.filter((job) => job.id !== id));
    try {
      await removeSavedJob(id);
    } catch (cause) {
      setJobs(before);
      setError(cause instanceof Error ? cause.message : "Could not remove the job.");
    }
  }, [jobs]);

  const toggle = useCallback(
    async (job: Job) => {
      if (jobs.some((item) => item.id === job.id)) {
        await remove(job.id);
        return;
      }
      setError(null);
      setJobs((current) => [job, ...current]);
      try {
        await saveJob(job);
      } catch (cause) {
        setJobs((current) => current.filter((item) => item.id !== job.id));
        setError(cause instanceof Error ? cause.message : "Could not save the job.");
      }
    },
    [jobs, remove],
  );

  const value = useMemo<SavedJobs>(
    () => ({ jobs, isSaved: (id) => jobs.some((job) => job.id === id), toggle, remove, error }),
    [jobs, toggle, remove, error],
  );

  return <SavedJobsContext.Provider value={value}>{children}</SavedJobsContext.Provider>;
}

export function useSavedJobs(): SavedJobs | null {
  return useContext(SavedJobsContext);
}
