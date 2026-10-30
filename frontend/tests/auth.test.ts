import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkPassword, DEFAULT_POLICY } from '../src/pages/auth/fields';
import { avatarUrl, resetAvatarCache, setAvatarVersion } from '../src/lib/avatars';

describe('password checklist mirrors the server policy', () => {
  it('lists every server rule plus the minimum length', () => {
    const { items } = checkPassword('', DEFAULT_POLICY);
    expect(items.map((i) => i.id)).toEqual(['length', 'upper', 'lower', 'digit']);
    expect(items[0].label).toBe('At least 10 characters');
  });

  it('only passes when every rule is met', () => {
    expect(checkPassword('short1A', DEFAULT_POLICY).meetsPolicy).toBe(false);
    expect(checkPassword('alllowercase1', DEFAULT_POLICY).meetsPolicy).toBe(false);
    expect(checkPassword('NoDigitsHereAtAll', DEFAULT_POLICY).meetsPolicy).toBe(false);
    expect(checkPassword('Research2026x', DEFAULT_POLICY).meetsPolicy).toBe(true);
  });

  it('never calls a failing password strong, however long', () => {
    const long = 'a'.repeat(40);
    expect(checkPassword(long, DEFAULT_POLICY).level).toBe(1);
  });

  it('rates passing passwords by length and symbols', () => {
    expect(checkPassword('Research2026', DEFAULT_POLICY).level).toBe(2);
    expect(checkPassword('Research2026!', DEFAULT_POLICY).level).toBe(3);
    expect(checkPassword('Glacier-Rivers-2026-Flow', DEFAULT_POLICY).level).toBe(4);
  });
});

describe('profile picture URLs', () => {
  afterEach(() => {
    resetAvatarCache();
    vi.restoreAllMocks();
  });

  it('embed the version so a changed picture is never served from cache', () => {
    expect(avatarUrl('usr_0123456789abcdef', 'v2')).toBe('/api/v1/users/usr_0123456789abcdef/avatar?v=v2');
  });

  it('accepts a known version without asking the server', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    setAvatarVersion('usr_0123456789abcdef', 'abc');
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
