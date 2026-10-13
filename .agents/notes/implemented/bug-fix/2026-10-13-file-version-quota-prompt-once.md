# 版本历史存满时，自动保存的升级提醒每个标签页只弹一次

Status: implemented（issue #184 的编辑器部分）

## Problem

文件的版本历史达到套餐上限后，`PUT /files` 仍保存正文，只返回 `version_quota_exceeded`。`Editor.tsx` 在每次保存成功后都弹 `toast` 并打开升级弹窗；自动保存会反复走到这里，作者关掉弹窗后继续写作又被打断，曝光统计也因此重复。

## Decision

`lib/upgradeTriggerStrategy.claimAutoUpgradePrompt(userId, kind)` 用 sessionStorage 记录「本标签页、该账号、该限制类型已主动提醒过」，存储不可用时退回本页内存。编辑器只在首次领取成功时弹 `toast` 与升级弹窗；之后的自动保存和手动保存都照常成功、不再主动打断，重新挂载编辑器也不再弹。领取发生在打开弹窗之前，若保存完成时编辑器已卸载，本标签页只会看到那一次 toast。键里带账号 id，同一标签页切换账号会重新提醒。保存本身因版本额度失败（`ERR_QUOTA_FILE_VERSIONS_EXCEEDED`）和作者主动恢复历史版本仍每次反馈。

## Alternatives considered

- **组件内 `useRef` 去重**：最强理由是改动最小。被否：重新挂载（切换文件、项目）后会再次弹出，正是 issue 指出的重复来源。
- **整个账号永久只提醒一次（localStorage）**：最强理由是最少打扰。被否：作者换个时间回来时完全看不到为何没有新版本，也跨标签页、跨会话掩盖真实展示。
- **只去掉弹窗、保留每次的 toast**：最强理由是保留文字说明。被否：自动保存频繁，toast 同样是重复打断。

## Consequences

- 收益：额度已满后的写作不再被反复打断，正文保存不受影响；升级弹窗曝光按真实主动展示计。
- 代价：同一标签页里之后的保存不再提示「这次没有生成新版本」，依赖版本历史面板呈现。#184 的曝光口径统一、其他入口的频控与转化核对未包含在本次。

## Verification

`apps/web`：`vitest run src/components/__tests__/Editor.history.test.tsx`：同账号连续保存与重新挂载只提醒一次、正文每次保存成功，切换账号重新提醒；去掉领取判断后该例失败。
