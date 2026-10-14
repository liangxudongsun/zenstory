import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { claimPreferredProjectType, clearPreferredProjectType, getPreferredProjectType,
  PREFERRED_PROJECT_TYPE_STORAGE_KEY as KEY, PREFERRED_PROJECT_TYPE_TTL_MS as TTL,
  setPreferredProjectType } from '../preferredProjectType';

beforeEach(() => localStorage.clear());
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe('owned project type memory and anonymous entry', () => {
  it('claims an explicit entry once, ahead of existing account memory', () => {
    setPreferredProjectType('novel', 'A');
    setPreferredProjectType('screenplay', 'B');
    setPreferredProjectType('short');
    claimPreferredProjectType('A');
    claimPreferredProjectType('B');
    expect(getPreferredProjectType('A')).toBe('short');
    expect(getPreferredProjectType('B')).toBe('screenplay');
    expect(getPreferredProjectType()).toBeNull();
  });

  it('does not assign an unowned legacy device value to the next account', () => {
    localStorage.setItem(KEY, JSON.stringify({ type: 'short', ts: Date.now() }));
    claimPreferredProjectType('B');
    expect(getPreferredProjectType('B')).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('expires only the affected account record', () => {
    localStorage.setItem(`${KEY}:A`, JSON.stringify({ type: 'short', ts: Date.now() - TTL - 1 }));
    setPreferredProjectType('screenplay', 'B');
    expect(getPreferredProjectType('A')).toBeNull();
    expect(localStorage.getItem(`${KEY}:A`)).toBeNull();
    expect(getPreferredProjectType('B')).toBe('screenplay');
  });

  it.each(['not json', JSON.stringify({ type: 'poem', ts: Date.now() }),
    JSON.stringify({ type: 'novel', ts: Date.now() + TTL + 60_000 })])('ignores and removes invalid owned memory %s', raw => {
    localStorage.setItem(`${KEY}:A`, raw);
    expect(getPreferredProjectType('A')).toBeNull();
    expect(localStorage.getItem(`${KEY}:A`)).toBeNull();
  });

  it('clearing one account leaves other accounts and public entry intact', () => {
    setPreferredProjectType('short', 'A');
    setPreferredProjectType('screenplay', 'B');
    setPreferredProjectType('novel');
    clearPreferredProjectType('A');
    expect(getPreferredProjectType('A')).toBeNull();
    expect(getPreferredProjectType('B')).toBe('screenplay');
    expect(getPreferredProjectType()).toBe('novel');
  });

  it('does not block authentication or creation when storage is unavailable', () => {
    for (const method of ['getItem', 'setItem', 'removeItem'] as const) {
      vi.spyOn(localStorage, method).mockImplementation(() => { throw new Error('storage unavailable'); });
    }
    expect(() => setPreferredProjectType('short', 'A')).not.toThrow();
    expect(() => claimPreferredProjectType('A')).not.toThrow();
    expect(getPreferredProjectType('A')).toBeNull();
  });
});
