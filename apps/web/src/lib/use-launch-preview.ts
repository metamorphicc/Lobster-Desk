"use client";

import { useEffect, useState } from "react";
import { isLaunchPreview, launchFigures } from "./launch-preview";
import { LOCAL_LAUNCH_PREVIEW_ENABLED } from "./preview-settings";

export function useLaunchPreview(blocked: boolean) {
  const [enabled, setEnabled] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const sync = () => setEnabled(isLaunchPreview(window.location.href, blocked, LOCAL_LAUNCH_PREVIEW_ENABLED,
      process.env.NEXT_PUBLIC_HOSTED_PREVIEW === "true"));
    sync(); window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, [blocked]);
  useEffect(() => {
    setTick(0);
    if (!enabled || blocked) return;
    const timer = setInterval(() => setTick(t => t + 1), 6000);
    return () => clearInterval(timer);
  }, [enabled, blocked]);
  return enabled && !blocked ? launchFigures(tick) : null;
}
