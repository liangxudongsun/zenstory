export type UpgradeTriggerStage =
  | "normal"
  | "reminder_50"
  | "reminder_80"
  | "blocked";

export interface UpgradeUsageSnapshot {
  used: number;
  limit: number;
}

export function resolveUpgradeTriggerStage({
  used,
  limit,
}: UpgradeUsageSnapshot): UpgradeTriggerStage {
  if (limit <= 0 || limit === -1) return "normal";

  const ratio = used / limit;
  if (ratio >= 1) return "blocked";
  if (ratio >= 0.8) return "reminder_80";
  if (ratio >= 0.5) return "reminder_50";
  return "normal";
}

export function buildStagedUpgradeSource(
  baseSource: string,
  stage: UpgradeTriggerStage
): string {
  const normalizedBase = baseSource.trim();
  if (!normalizedBase) return "";
  if (stage === "normal") return normalizedBase;
  return `${normalizedBase}:${stage}`;
}

const AUTO_PROMPT_KEY_PREFIX = "zenstory-upgrade-auto-prompted";
const autoPromptedWithoutStorage = new Set<string>();

/**
 * 保存成功时附带的主动升级提醒（例如正文已保存、只是版本快照额度满了）：同一账号、
 * 同一限制类型在当前标签页会话内只弹一次，作者关掉后不会被之后的自动或手动保存、
 * 重新挂载或切换项目再次打断。真正被额度挡下的操作（保存失败、恢复历史版本）不走
 * 这里，每次都照常反馈。sessionStorage 不可用时退回本页内存。返回 true 表示这次可以提醒。
 */
export function claimAutoUpgradePrompt(userId: string | null, kind: string, period?: string): boolean {
  const key = `${AUTO_PROMPT_KEY_PREFIX}:${kind}:${userId ?? "anonymous"}${period ? `:${period}` : ""}`;
  try {
    if (sessionStorage.getItem(key)) {
      autoPromptedWithoutStorage.add(key);
      return false;
    }
    sessionStorage.setItem(key, "1");
    autoPromptedWithoutStorage.add(key);
    return true;
  } catch {
    if (autoPromptedWithoutStorage.has(key)) return false;
    autoPromptedWithoutStorage.add(key);
    return true;
  }
}
