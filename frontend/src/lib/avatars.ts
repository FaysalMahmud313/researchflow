import { useEffect, useState } from 'react';
import { API_BASE_URL, api } from '../services/apiClient';

/**
 * Profile-picture versions by user id. Components ask for ids as they render; the ids
 * requested in the same tick are fetched in one batch (GET /users/avatars). A version is
 * part of the image URL, so a changed picture is never served from a stale cache.
 */
type Version = string | null; // null: the user has no picture
const versions = new Map<string, Version>();
const listeners = new Map<string, Set<(v: Version) => void>>();
const pending = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;

function publish(id: string, v: Version): void {
  versions.set(id, v);
  listeners.get(id)?.forEach((fn) => fn(v));
}

async function flush(): Promise<void> {
  timer = null;
  const ids = [...pending];
  pending.clear();
  for (let i = 0; i < ids.length; i += 200) {
    const batch = ids.slice(i, i + 200);
    try {
      const res = await api.get<{ avatars: Record<string, string> }>(`/users/avatars?ids=${batch.join(',')}`);
      batch.forEach((id) => publish(id, res.avatars[id] ?? null));
    } catch {
      batch.forEach((id) => publish(id, null)); // initials are a fine fallback
    }
  }
}

function request(id: string): void {
  if (versions.has(id) || pending.has(id)) return;
  pending.add(id);
  if (!timer) timer = setTimeout(() => void flush(), 0);
}

/** Record a known version (e.g. right after the user changes their own picture). */
export function setAvatarVersion(userId: string, version: string): void {
  publish(userId, version || null);
}

export function avatarUrl(userId: string, version: string): string {
  return `${API_BASE_URL}/users/${encodeURIComponent(userId)}/avatar?v=${encodeURIComponent(version)}`;
}

export function useAvatarVersion(userId: string | undefined | null, known?: string | null): Version {
  const [v, setV] = useState<Version>(() => (userId ? versions.get(userId) ?? null : null));
  useEffect(() => {
    if (!userId) return;
    if (known !== undefined) {
      publish(userId, known || null);
    } else {
      request(userId);
    }
    setV(versions.get(userId) ?? null);
    const set = listeners.get(userId) ?? new Set();
    set.add(setV);
    listeners.set(userId, set);
    return () => {
      set.delete(setV);
    };
  }, [userId, known]);
  return v;
}

/** Forget everything (sign-out), so the next account starts clean. */
export function resetAvatarCache(): void {
  versions.clear();
  pending.clear();
}
