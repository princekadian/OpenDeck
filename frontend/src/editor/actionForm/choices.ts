// Live choices for action settings (audio devices, displays, running apps), loaded on demand
// and cached for the editor session. "Refresh" re-reads them from the PC.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Choice, type RunningApp } from "../api";

type Loader<T> = () => Promise<T>;
const cache = new Map<string, Promise<unknown>>();

function useChoices<T>(key: string, load: Loader<T>): { data: T | null; error: string | null; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let alive = true;
    if (!cache.has(key)) cache.set(key, load());
    (cache.get(key) as Promise<T>)
      .then((value) => alive && (setData(value), setError(null)))
      .catch((e) => {
        cache.delete(key);
        if (alive) setError(e instanceof ApiError ? e.message : "Couldn't load the list from the PC.");
      });
    return () => {
      alive = false;
    };
  }, [key, load, version]);

  const refresh = useCallback(() => {
    cache.delete(key);
    setVersion((v) => v + 1);
  }, [key]);

  return { data, error, refresh };
}

const loadOutputs = () => api.audioDevices("output").then((r) => r.devices);
const loadInputs = () => api.audioDevices("input").then((r) => r.devices);
const loadDisplays = () => api.displays().then((r) => r.displays);
const loadApps = () => api.runningApps().then((r) => r.apps);

export const useAudioDevices = (flow: "output" | "input") =>
  useChoices<Choice[]>(`audio:${flow}`, flow === "output" ? loadOutputs : loadInputs);
export const useDisplays = () => useChoices<Choice[]>("displays", loadDisplays);
export const useRunningApps = () => useChoices<RunningApp[]>("apps", loadApps);

const loadObsScenes = () => api.obsScenes().then((r) => r.items);
const loaders = new Map<string, () => Promise<string[]>>();
function loader(key: string, make: () => Promise<string[]>) {
  if (!loaders.has(key)) loaders.set(key, make);
  return loaders.get(key)!;
}

export const useObsScenes = () => useChoices<string[]>("obs:scenes", loadObsScenes);
export const useObsInputs = (kind: "all" | "audio" | "video") =>
  useChoices<string[]>(`obs:inputs:${kind}`, loader(`inputs:${kind}`, () => api.obsInputs(kind).then((r) => r.items)));
/** Sources in a scene ("" = the live scene); "video" keeps only camera-type inputs. */
export const useObsSources = (scene: string, kind: string) =>
  useChoices<string[]>(
    `obs:sources:${scene}:${kind}`,
    loader(`sources:${scene}:${kind}`, async () => {
      const sources = (await api.obsSources(scene)).items;
      if (kind !== "video") return sources;
      const cameras = new Set((await api.obsInputs("video")).items);
      const only = sources.filter((s) => cameras.has(s));
      return only.length ? only : sources;
    }),
  );

/** For tests. */
export function clearChoiceCache(): void {
  cache.clear();
}
