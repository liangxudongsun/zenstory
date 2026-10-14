import { describe, expect, it, vi } from "vitest";

import {
  buildStagedUpgradeSource,
  claimAutoUpgradePrompt,
  resolveUpgradeTriggerStage,
} from "../upgradeTriggerStrategy";

describe("upgradeTriggerStrategy", () => {
  it("returns normal stage when usage is below 50%", () => {
    expect(resolveUpgradeTriggerStage({ used: 4, limit: 20 })).toBe("normal");
  });

  it("returns reminder_50 stage when usage reaches 50%", () => {
    expect(resolveUpgradeTriggerStage({ used: 10, limit: 20 })).toBe("reminder_50");
  });

  it("returns reminder_80 stage when usage reaches 80%", () => {
    expect(resolveUpgradeTriggerStage({ used: 16, limit: 20 })).toBe("reminder_80");
  });

  it("returns blocked stage when usage reaches limit", () => {
    expect(resolveUpgradeTriggerStage({ used: 20, limit: 20 })).toBe("blocked");
  });

  it("builds staged source suffix", () => {
    expect(buildStagedUpgradeSource("settings_subscription_upgrade", "reminder_80")).toBe(
      "settings_subscription_upgrade:reminder_80"
    );
    expect(buildStagedUpgradeSource("settings_subscription_upgrade", "normal")).toBe(
      "settings_subscription_upgrade"
    );
  });
});


it("isolates proactive claims by account, kind and period without suppressing another day", () => {
  sessionStorage.clear();
  expect(claimAutoUpgradePrompt("a", "chat", "day1")).toBe(true);
  expect(claimAutoUpgradePrompt("a", "chat", "day1")).toBe(false);
  expect(claimAutoUpgradePrompt("a", "chat", "day2")).toBe(true);
  expect(claimAutoUpgradePrompt("b", "chat", "day1")).toBe(true);
  expect(claimAutoUpgradePrompt("a", "versions", "day1")).toBe(true);
  sessionStorage.clear();
});

it("retains the in-memory proactive claim if sessionStorage later fails", () => {
  sessionStorage.clear();
  expect(claimAutoUpgradePrompt("storage-a", "chat", "day1")).toBe(true);
  const read = vi.spyOn(sessionStorage, 'getItem').mockImplementation(() => { throw new Error('Storage unavailable'); });
  expect(claimAutoUpgradePrompt("storage-a", "chat", "day1")).toBe(false);
  expect(claimAutoUpgradePrompt("storage-a", "chat", "day2")).toBe(true);
  read.mockRestore();
  sessionStorage.clear();
});
