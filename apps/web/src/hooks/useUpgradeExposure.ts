import { useEffect, useRef } from 'react';
import { subscriptionQueryKeys } from '../lib/subscriptionApi';
import { trackUpgradeExpose, type UpgradeFunnelSurface } from '../lib/upgradeAnalytics';

// A visibility lease ends after the current commit: StrictMode's effect replay
// and synchronous route replacement do not invent a second visible impression.
// A real disappearance releases it; this is deliberately not session-wide dedupe.
const visibleEntries = new Map<string, Set<symbol>>();

function acquire(key: string, source: string, surface: UpgradeFunnelSurface, placement: string): () => void {
  let owners = visibleEntries.get(key);
  if (!owners) {
    owners = new Set();
    visibleEntries.set(key, owners);
    trackUpgradeExpose(source, surface, { placement });
  }
  const owner = Symbol();
  owners.add(owner);
  return () => {
    owners.delete(owner);
    queueMicrotask(() => {
      if (owners.size === 0 && visibleEntries.get(key) === owners) visibleEntries.delete(key);
    });
  };
}

/** Count actual visible surfaces once, with account, stage, placement and period isolation. */
export function useUpgradeExposure({
  enabled = true, source, surface, placement, period = '',
}: { enabled?: boolean; source?: string; surface: UpgradeFunnelSurface; placement: string; period?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const account = subscriptionQueryKeys.status()[1];
  const key = JSON.stringify([account, source, surface, placement, period]);
  useEffect(() => {
    const element = ref.current;
    if (!enabled || !source || !element) return;
    let intersecting = typeof IntersectionObserver === 'undefined' || visibleEntries.has(key);
    let release: (() => void) | undefined;
    const update = () => {
      const visible = intersecting && document.visibilityState !== 'hidden';
      if (visible && !release) release = acquire(key, source, surface, placement);
      else if (!visible && release) { release(); release = undefined; }
    };
    const observer = typeof IntersectionObserver === 'undefined' ? undefined : new IntersectionObserver(entries => {
      intersecting = entries.some(entry => entry.isIntersecting);
      update();
    });
    observer?.observe(element);
    document.addEventListener('visibilitychange', update);
    update();
    return () => {
      observer?.disconnect();
      document.removeEventListener('visibilitychange', update);
      release?.();
    };
  }, [enabled, source, surface, placement, key]);
  return ref;
}
