import type { ProjectType } from "../types";

/**
 * Account-owned creation memory, plus a one-time anonymous landing-page choice.
 * Authentication claims an explicit anonymous choice before its UI mounts; an
 * unowned legacy device value must never become another account's preference.
 * Storage failures (private mode, quota, blocked site data) only lose the
 * preference; the dashboard then falls back to "novel".
 */
export const PREFERRED_PROJECT_TYPE_STORAGE_KEY = "zenstory_preferred_project_type";
export const PREFERRED_PROJECT_TYPE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

const PREFERABLE_PROJECT_TYPES: readonly ProjectType[] = ["novel", "short", "screenplay"];

interface StoredPreferredProjectType {
  type: ProjectType;
  ts: number;
  source?: "entry";
}

const storageKey = (userId?: string | null) => userId
  ? `${PREFERRED_PROJECT_TYPE_STORAGE_KEY}:${userId}`
  : PREFERRED_PROJECT_TYPE_STORAGE_KEY;

export function isPreferableProjectType(value: unknown): value is ProjectType {
  return typeof value === "string" && PREFERABLE_PROJECT_TYPES.includes(value as ProjectType);
}

export function setPreferredProjectType(type: ProjectType, userId?: string | null): void {
  if (!isPreferableProjectType(type)) return;
  try {
    const record: StoredPreferredProjectType = { type, ts: Date.now(), ...(!userId ? { source: "entry" as const } : {}) };
    localStorage.setItem(storageKey(userId), JSON.stringify(record));
  } catch {
    // Preference is a convenience; losing it is harmless.
  }
}

function readPreference(userId?: string | null, now: number = Date.now()): StoredPreferredProjectType | null {
  let raw: string | null;
  try {
    raw = localStorage.getItem(storageKey(userId));
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<StoredPreferredProjectType> | null;
    if (
      !parsed ||
      !isPreferableProjectType(parsed.type) ||
      typeof parsed.ts !== "number" ||
      !Number.isFinite(parsed.ts) ||
      now - parsed.ts > PREFERRED_PROJECT_TYPE_TTL_MS ||
      parsed.ts - now > PREFERRED_PROJECT_TYPE_TTL_MS
    ) {
      clearPreferredProjectType(userId);
      return null;
    }
    return parsed as StoredPreferredProjectType;
  } catch {
    clearPreferredProjectType(userId);
    return null;
  }
}

export function getPreferredProjectType(userId?: string | null, now: number = Date.now()): ProjectType | null {
  return readPreference(userId, now)?.type ?? null;
}

export function claimPreferredProjectType(userId: string): void {
  if (!userId) return;
  const entry = readPreference();
  // Older records mixed prior accounts with anonymous entry. Their owner is
  // unknowable; only a newly explicit public-entry choice can be transferred.
  if (entry?.source === "entry") setPreferredProjectType(entry.type, userId);
  clearPreferredProjectType();
}

export function clearPreferredProjectType(userId?: string | null): void {
  try {
    localStorage.removeItem(storageKey(userId));
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}
