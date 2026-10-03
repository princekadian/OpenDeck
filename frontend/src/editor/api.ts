// Typed client for the PC-only editor API (/api/admin). See backend server/admin_api.py.

import type { MonitorMetricId, SystemMonitorPayload } from "../protocol/messages";

export interface EditorProfile {
  id: string;
  name: string;
  description: string;
  iconRef: string | null;
  sortOrder: number;
}

export interface EditorPage {
  id: string;
  profileId: string;
  name: string;
  iconRef: string | null;
  sortOrder: number;
  /** "monitor" pages show System Monitoring instead of buttons. */
  kind: "deck" | "monitor";
}

export interface MonitoringSettings {
  intervalMs: number;
  tiles: Array<{ metric: MonitorMetricId; enabled: boolean }>;
}

export interface EditorButton {
  id: string;
  pageId: string;
  /** Folder this button is inside; null = directly on the page. */
  parentId: string | null;
  /** "folder" buttons contain other buttons and never run an action. */
  kind: ButtonKind;
  sortOrder: number;
  label: string;
  description: string;
  iconRef: string | null;
  actionType: string;
  actionConfig: Record<string, unknown>;
  appearance: Record<string, unknown>;
  enabled: boolean;
}

/** JSON Schema subset produced by the backend's Pydantic action models. */
export interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  items?: SchemaProperty;
  $ref?: string;
  allOf?: SchemaProperty[];
  anyOf?: SchemaProperty[];
  properties?: Record<string, SchemaProperty>;
  required?: string[];
  /** Editor control hint, e.g. exe | app | file | folder | url | multiline | code | audio-output |
   *  audio-input | display | page | profile | hotkey | key | key-combo | steps | action. */
  widget?: string;
  /** Unit shown after a number input ("%", "ms", "px", "min", "s"). */
  unit?: string;
  /** Friendly labels for enum values. */
  labels?: Record<string, string>;
  /** Show the field only when another field has one of these values. */
  showWhen?: Record<string, string[]>;
}

export interface ConfigSchema extends SchemaProperty {
  $defs?: Record<string, SchemaProperty>;
}

export interface ActionInfo {
  type: string;
  displayName: string;
  description: string;
  category: string;
  icon: string;
  status: "available" | "coming_soon";
  trustedOnly: boolean;
  /** Test asks first: it would end the session or close work on this PC. */
  destructive: boolean;
  stateful: boolean;
  configSchema: ConfigSchema;
}

export interface KeyInfo {
  name: string;
  label: string;
  group: string;
}

export interface ActionCategory {
  id: string;
  label: string;
}

export interface EditorTree {
  activeProfileId: string | null;
  profiles: EditorProfile[];
  pages: EditorPage[];
  buttons: EditorButton[];
  categories: ActionCategory[];
  actions: ActionInfo[];
  keys: KeyInfo[];
}

export interface Choice {
  id: string;
  name: string;
  isDefault?: boolean;
  primary?: boolean;
}

export interface ObsInfo {
  status: "disabled" | "connecting" | "connected" | "auth_failed" | "unreachable";
  message: string;
  version: string;
  settings: { enabled: boolean; host: string; port: number; hasPassword: boolean };
}

export interface RunningApp {
  path: string;
  title: string;
  name: string;
}

export type ButtonKind = "action" | "folder";

export interface ButtonDraft {
  kind: ButtonKind;
  label: string;
  description: string;
  iconRef: string | null;
  actionType: string;
  actionConfig: Record<string, unknown>;
  enabled: boolean;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, contentType = "application/json"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/admin${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": contentType },
      body: body === undefined ? undefined : contentType === "application/json" ? JSON.stringify(body) : (body as BodyInit),
    });
  } catch {
    throw new ApiError(0, "OFFLINE", "Can't reach the app. Check that it is running on this PC.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    if (response.status === 422 && Array.isArray(detail)) {
      const fields: Record<string, string> = {};
      for (const issue of detail) fields[String(issue.loc?.at(-1) ?? "form")] = String(issue.msg ?? "Invalid value.").replace(/^Value error, /, "");
      throw new ApiError(422, "INVALID_INPUT", "Check the highlighted fields.", fields);
    }
    throw new ApiError(
      response.status,
      detail?.code ?? "ERROR",
      detail?.message ?? (typeof detail === "string" ? detail : "Something went wrong."),
      detail?.fields ?? {},
    );
  }
  return data as T;
}

export const api = {
  tree: () => request<EditorTree>("GET", "/config"),

  createProfile: (name: string) => request<EditorProfile>("POST", "/profiles", { name }),
  updateProfile: (p: EditorProfile, name: string) =>
    request<EditorProfile>("PATCH", `/profiles/${p.id}`, { name, description: p.description, iconRef: p.iconRef }),
  deleteProfile: (id: string) => request<void>("DELETE", `/profiles/${id}`),
  duplicateProfile: (id: string) => request<EditorProfile>("POST", `/profiles/${id}/duplicate`),
  reorderProfiles: (ids: string[]) => request<void>("PUT", "/profiles-order", { ids }),
  setActiveProfile: (profileId: string) => request<void>("PUT", "/active-profile", { profileId }),

  createPage: (profileId: string, name: string, kind: EditorPage["kind"] = "deck") =>
    request<EditorPage>("POST", `/profiles/${profileId}/pages`, { name, kind }),
  updatePage: (p: EditorPage, name: string) => request<EditorPage>("PATCH", `/pages/${p.id}`, { name, iconRef: p.iconRef }),
  deletePage: (id: string) => request<void>("DELETE", `/pages/${id}`),
  duplicatePage: (id: string) => request<EditorPage>("POST", `/pages/${id}/duplicate`),
  reorderPages: (profileId: string, ids: string[]) => request<void>("PUT", `/profiles/${profileId}/pages-order`, { ids }),

  createButton: (pageId: string, draft: ButtonDraft, parentId: string | null = null) =>
    request<EditorButton>("POST", `/pages/${pageId}/buttons`, { ...draft, parentId }),
  updateButton: (id: string, draft: ButtonDraft) => request<EditorButton>("PATCH", `/buttons/${id}`, draft),
  setButtonEnabled: (id: string, enabled: boolean) => request<EditorButton>("PUT", `/buttons/${id}/enabled`, { enabled }),
  deleteButton: (id: string) => request<void>("DELETE", `/buttons/${id}`),
  duplicateButton: (id: string) => request<EditorButton>("POST", `/buttons/${id}/duplicate`),
  moveButton: (id: string, pageId: string, parentId: string | null = null) =>
    request<EditorButton>("POST", `/buttons/${id}/move`, { pageId, parentId }),
  reorderButtons: (pageId: string, ids: string[], parentId: string | null = null) =>
    request<void>("PUT", `/pages/${pageId}/buttons-order`, { ids, parentId }),

  testAction: (actionType: string, actionConfig: Record<string, unknown>) =>
    request<{ success: boolean; message?: string; error?: { code: string; message: string } }>("POST", "/actions/test", {
      actionType,
      actionConfig,
    }),
  pick: (kind: "exe" | "file" | "folder") => request<{ path: string | null }>("POST", "/pick", { kind }),
  appInfo: (path: string) => request<{ name: string; iconRef: string | null }>("POST", "/app-info", { path }),
  uploadIcon: (png: Blob) => request<{ iconRef: string }>("POST", "/icons", png, "image/png"),
  audioDevices: (flow: "output" | "input") => request<{ devices: Choice[] }>("GET", `/audio-devices?flow=${flow}`),
  displays: () => request<{ displays: Choice[] }>("GET", "/displays"),
  runningApps: () => request<{ apps: RunningApp[] }>("GET", "/running-apps"),
  monitoring: () => request<{ settings: MonitoringSettings; metrics: MonitorMetricId[] }>("GET", "/monitoring"),
  saveMonitoring: (settings: MonitoringSettings) =>
    request<{ settings: MonitoringSettings; metrics: MonitorMetricId[] }>("PUT", "/monitoring", settings),
  monitoringLive: () => request<SystemMonitorPayload>("GET", "/monitoring/live"),
  obs: () => request<ObsInfo>("GET", "/obs"),
  saveObs: (body: { enabled: boolean; host: string; port: number; password: string | null }) => request<ObsInfo>("PUT", "/obs", body),
  obsScenes: () => request<{ items: string[] }>("GET", "/obs/scenes"),
  obsInputs: (kind: "all" | "audio" | "video") => request<{ items: string[] }>("GET", `/obs/inputs?kind=${kind}`),
  obsSources: (scene: string) => request<{ items: string[] }>("GET", `/obs/sources?scene=${encodeURIComponent(scene)}`),
};
