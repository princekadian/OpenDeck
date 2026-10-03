// Helpers for the JSON Schemas generated from the backend's action config models.

import type { ActionInfo, ConfigSchema, SchemaProperty } from "../api";

export function resolve(prop: SchemaProperty, root: ConfigSchema): SchemaProperty {
  const ref = prop.$ref ?? prop.allOf?.[0]?.$ref;
  if (!ref) return prop;
  const target = root.$defs?.[ref.replace("#/$defs/", "")] ?? {};
  return { ...target, ...prop, $ref: undefined };
}

export function properties(schema: ConfigSchema): Array<[string, SchemaProperty]> {
  return Object.entries(schema.properties ?? {}).map(([key, prop]) => [key, resolve(prop, schema)]);
}

/** Default settings for a newly chosen action, so the form shows real starting values. */
export function defaultConfig(action: ActionInfo | undefined): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  if (!action) return config;
  for (const [key, prop] of properties(action.configSchema)) {
    if (prop.default !== undefined) config[key] = structuredCloneSafe(prop.default);
  }
  return config;
}

export function isVisible(prop: SchemaProperty, config: Record<string, unknown>, schema: ConfigSchema): boolean {
  if (!prop.showWhen) return true;
  return Object.entries(prop.showWhen).every(([field, values]) => {
    const value = config[field] ?? schema.properties?.[field]?.default;
    return values.includes(String(value));
  });
}

function structuredCloneSafe<T>(value: T): T {
  return value === null || typeof value !== "object" ? value : (JSON.parse(JSON.stringify(value)) as T);
}

/** Actions that may be used as a Multi Action step or Toggle branch. */
export const COMPOSITE_TYPES = new Set(["multi_action", "toggle"]);
