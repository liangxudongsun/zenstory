import type { StreamRenderItem } from "../hooks/useChatStreaming";

/** Progress lines that only mean "working on it"; they say nothing once the round is over. */
const TRANSIENT_ITEM_TYPES = new Set<StreamRenderItem["type"]>(["thinking_status", "context", "router_thinking"]);

/**
 * Whether a round that ended early (error, dropped connection, stop) left anything worth a
 * bubble. A failed first message that only got as far as 「正在组装上下文…」 should not
 * leave an empty bubble next to the error card.
 */
export function hasSubstantiveDisplayItems(items: StreamRenderItem[]): boolean {
  return items.some((item) => !TRANSIENT_ITEM_TYPES.has(item.type));
}

/** How a stopped / interrupted round ended, as the server recorded it on the assistant message. */
export interface RoundStopOutcome {
  reason: 'user_stopped' | 'client_disconnected';
  /** Counted toward the daily AI messages (false: refunded). */
  charged: boolean;
  /** Something was written into a file before it ended. */
  savedOutput: boolean;
  /** Titles of blank files this round created and the server removed. */
  removedFiles: string[];
  /**
   * Files this round wrote text into, in order (`stop_outcome.written_files`). `words` is the
   * editor word count of what this round wrote, null when unknown (an edit). Empty for older
   * messages and for writes the server cannot name (parallel chapters, deletions).
   */
  writtenFiles: RoundWrittenFile[];
}

export interface RoundWrittenFile {
  title: string;
  words: number | null;
}

function parseWrittenFiles(raw: unknown): RoundWrittenFile[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') return [];
    const { title, words } = item as { title?: unknown; words?: unknown };
    if (typeof title !== 'string' || !title) return [];
    return [{ title, words: typeof words === 'number' && Number.isFinite(words) ? words : null }];
  });
}

/**
 * Reads `message_metadata.stop_outcome` (written by the server after a stop / disconnect
 * settles; see agent/core/round_outcome.py). Returns null for every other message.
 */
export function parseRoundStopOutcome(metadata: unknown): RoundStopOutcome | null {
  let parsed: unknown = metadata;
  if (typeof metadata === 'string') {
    try {
      parsed = JSON.parse(metadata);
    } catch {
      return null;
    }
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const outcome = (parsed as { stop_outcome?: unknown }).stop_outcome;
  if (!outcome || typeof outcome !== 'object') return null;
  const raw = outcome as Record<string, unknown>;
  if (raw.reason !== 'user_stopped' && raw.reason !== 'client_disconnected') return null;
  return {
    reason: raw.reason,
    charged: raw.charged !== false,
    savedOutput: raw.saved_output === true,
    removedFiles: Array.isArray(raw.removed_files)
      ? raw.removed_files.filter((title): title is string => typeof title === 'string' && Boolean(title))
      : [],
    writtenFiles: parseWrittenFiles(raw.written_files),
  };
}
