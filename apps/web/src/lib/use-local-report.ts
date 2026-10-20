"use client";

import { useEffect, useState } from "react";

/** Read-only reports. A refresh never triggers research, signatures or transfers. */
export function useLocalReport<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const response = await fetch(path, { cache: "no-store", signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
        if (!response.ok) throw new Error("Unavailable report");
        const result = await response.json() as T;
        if (!controller.signal.aborted) { setData(result); setError(""); }
      } catch {
        if (!controller.signal.aborted) { setData(null); setError("This report is temporarily unavailable. Please retry."); }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
        busy = false;
      }
    }
    setData(null); setLoading(true);
    void load();
    const timer = setInterval(() => { void load(); }, 15000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [path, revision]);
  return { data, error, loading, refresh: () => setRevision(value => value + 1) };
}
