import { useTranslation } from 'react-i18next';
import { CirclePause } from 'lucide-react';
import type { RoundStopOutcome, RoundWrittenFile } from '../lib/chatRoundEnd';

/** At most this many written files are named; the rest are counted. */
const NAMED_WRITTEN_FILES = 3;

/**
 * The grey end-of-round line on a stopped / interrupted assistant message after a refresh,
 * e.g. 「已停止 · 未计入今日 AI 消息」 / 「已停止 · 已写入的内容已保存 · 本条计入今日 AI 消息」 / 「已中断」:
 * the same wording as the live stop note. Pro (no daily limit) never mentions the daily count.
 * When the server named the files this round wrote, the note says which ones instead of only
 * 「已写入的内容已保存」: 「已中断 · 已保存《第2章》3,120 字 · 本条计入今日 AI 消息」.
 */
export function RoundEndNote({ outcome, showDailyCount }: { outcome: RoundStopOutcome; showDailyCount: boolean }) {
  const { t, i18n } = useTranslation(['chat']);
  const savedText = outcome.writtenFiles.length > 0
    ? savedFilesText(t, outcome.writtenFiles, i18n?.language)
    : t('chat:panel.userStoppedSaved', { defaultValue: '已写入的内容已保存' });
  const parts = [
    outcome.reason === 'user_stopped'
      ? t('chat:panel.userStopped', { defaultValue: '已停止' })
      : t('chat:panel.roundInterrupted', { defaultValue: '已中断' }),
    !outcome.charged && showDailyCount
      ? t('chat:panel.roundNotCounted', { defaultValue: '未计入今日 AI 消息' })
      : null,
    outcome.charged && outcome.savedOutput ? savedText : null,
    outcome.charged && showDailyCount
      ? t('chat:panel.userStoppedCounted', { defaultValue: '本条计入今日 AI 消息' })
      : null,
    outcome.removedFiles.length > 0
      ? t('chat:panel.roundRemovedFiles', {
        defaultValue: '空白的《{{titles}}》已移除',
        titles: outcome.removedFiles.join(t('chat:panel.removedFilesJoiner', { defaultValue: '》《' })),
      })
      : null,
  ].filter(Boolean);

  return (
    <div
      className="mt-2 inline-flex items-center gap-1.5 text-xs text-[hsl(var(--text-secondary))]"
      data-testid="round-end-note"
    >
      <CirclePause size={14} className="shrink-0" />
      <span>{parts.join(' · ')}</span>
    </div>
  );
}

type Translate = ReturnType<typeof useTranslation>['t'];

/** 「已保存《第2章》3,120 字、《人物》等 5 个文件」 */
function savedFilesText(t: Translate, files: RoundWrittenFile[], language: string | undefined): string {
  let numberFormat: Intl.NumberFormat;
  try {
    numberFormat = new Intl.NumberFormat(language || undefined);
  } catch {
    numberFormat = new Intl.NumberFormat();
  }
  const named = files.slice(0, NAMED_WRITTEN_FILES).map(({ title, words }) => (
    words
      ? t('chat:panel.roundSavedFileWords', {
        defaultValue: '《{{title}}》{{words}} 字',
        title,
        words: numberFormat.format(words),
      })
      : t('chat:panel.roundSavedFile', { defaultValue: '《{{title}}》', title })
  ));
  let list = named.join(t('chat:panel.roundSavedFilesJoiner', { defaultValue: '、' }));
  if (files.length > named.length) {
    list = t('chat:panel.roundSavedFilesMore', {
      defaultValue: '{{files}}等 {{total}} 个文件',
      files: list,
      total: files.length,
      rest: files.length - named.length,
    });
  }
  return t('chat:panel.roundSavedFiles', { defaultValue: '已保存{{files}}', files: list });
}
