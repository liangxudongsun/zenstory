# 后台套餐卡片显示用户实际获得的权益

Status: implemented

## Problem

后台「订阅计划」卡片直接遍历数据库里的 `features` 原始 JSON，用户侧 `/plans`、`/catalog` 与额度检查则先经过 `resolve_plan_feature` 补默认值、`normalize_export_formats` 过滤格式，免费版每日 AI 次数还固定取代码默认值。生产上两边因此不一致：导出格式后台写 Free「txt, md」、Pro「txt, md, docx, pdf」，用户实际只有 TXT；免费版缺少 `custom_skills` 键，后台不显示，用户看到并被限制为 3；上下文窗口、自定义提示词、素材上传次数没有任何运行时读取，却被当成套餐差异展示；`materials_library_access` 不在标签表里，显示成原始键名。编辑框预填旧的 md/docx/pdf，严格 schema 只接受 `txt`，不改动直接保存也会 422。另外英文界面把自定义技能和每文件版本数的单位写成「projects」，文档仍承诺免费版可一次试拆前 20 章，而生产未开启 `MATERIAL_TRIAL_ENABLED`。

## Decision

- `GET /api/admin/plans` 在原字段外增加 `effective_features`，与用户侧 `/plans` 使用同一个 `_normalize_plan_features_for_response`。卡片只列运行时生效的键（每日 AI 次数、项目数、自定义技能、每文件版本数、素材库、每月素材拆解、灵感复用（开关打开时）、导出格式），取值来自 `effective_features`，并注明编辑框中是存储的原始配置。新增 `materials_library_access` 中英文标签。
- 管理端 `SubscriptionFeatures.export_formats` 接受任意字符串列表并按 `normalize_export_formats` 只保留支持的格式。原样回存旧数据不再 422，保存时顺带把 md/docx/pdf 清掉；非空列表规范化后一个支持格式都不剩（例如 `["pdf"]`）仍返回 422，避免把套餐存成不能导出。其他字段的严格校验不变。
- `file_version_service.check_user_version_quota` 改用 `quota_service.get_plan_feature` 解析每文件版本数，缺键时取该套餐自己的默认值（Pro 100），与卡片和 `/plans` 一致；生产两行都存了该键，行为不变。
- `getSubscriptionFeatureRows` 为自定义技能与版本数使用独立单位键 `skillsUnit` / `versionsUnit`（中文仍为「个」）。
- 文档中订阅权益表与 FAQ 的免费版素材拆解改为「不含」，素材库说明改为页面提供试拆时才可用的条件描述。修正两个显示名输入框重复的 `id`。

## Alternatives considered

- **直接修生产数据（补齐缺键、把导出格式改成 txt）**：最强理由是后台原样显示即可一致。被否：需要备份与单独授权的数据变更，且以后代码默认值或规范化规则再变时会再次漂移；显示服务端解析结果从根上消除差异。
- **前端自行复刻默认值与规范化**：最强理由是不改接口。被否：两套规则必然漂移，正是这次问题的来源。
- **继续展示未生效的键并标注「未生效」**：最强理由是信息完整。被否：卡片用于确认套餐差异，展示无效配置仍会误导；原始键在编辑框里可见。
- **让免费版每日次数改为读数据库**：最强理由是后台可直接调整。被否：涉及计费口径与回滚语义，单独提 issue 讨论；卡片显示有效值后至少不会误导。

## Consequences

- 收益：后台看到的就是用户看到、系统执行的权益；旧数据可以正常回存；英文单位与文档不再误导。
- 代价：卡片不再展示上下文窗口、自定义提示词、素材上传次数等存储键；免费版每日 AI 次数在后台修改后仍由代码决定（卡片显示有效值，修改不会生效），该行为另行跟踪。

## Verification

`apps/server`：`pytest tests/test_api/test_admin_plans.py`，按生产形状存储 free/pro 后 `effective_features` 等于用户侧 `/plans` 的 features，旧导出格式回存返回 200 并存为 `["txt"]`；去掉改动后两例失败。`test_admin_review_boundaries.py` 覆盖 `["pdf"]` 仍为 422；`test_round3_version_quota.py` 覆盖缺键 Pro 按 100 执行。`apps/web`：`SubscriptionPlanManagement.test.tsx` 覆盖卡片按有效值列出、素材库标签已翻译；`subscriptionEntitlements.test.ts` 覆盖英文单位。
