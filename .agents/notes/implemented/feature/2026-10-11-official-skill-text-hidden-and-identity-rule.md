# Agent Note: 官方技能正文不对用户公开、身份与保密规则写在代码里、每轮最多加载 3 个技能

Status: implemented

关联：[2026-10-11-agent-identity-reply-language-rewrite-in-place](../bug-fix/2026-10-11-agent-identity-reply-language-rewrite-in-place.md)（引入 `PRODUCT_IDENTITY_PROTOCOL`，当时不采用「禁止透露任何技能内容」，理由是技能全文在技能页面公开；本条把官方技能这一部分改为不公开）、[2026-10-05-skills-launch-hardening](2026-10-05-skills-launch-hardening.md)（`GET /public-skills/{id}` 回传全文、列表回传预览；本条起官方技能两者都不回传正文）、[2026-09-27-standard-skills-without-execution](../architecture/2026-09-27-standard-skills-without-execution.md)（技能渐进式加载）。

## Problem

- **官方技能正文对用户完全公开**：`public_skill.source = "official"` 的技能正文由 `GET /public-skills`（预览）、`GET /public-skills/{id}`（全文）、`GET /skills`、`GET /skills/my-skills`（已添加的技能，全文）原样返回；技能页、发现页和侧栏技能弹窗都直接渲染。`GET /skills/{id}/export` 导出 zip 再导入，就能把官方技能复制成自己的技能；资源文件也能逐个读取。所有者 2026-10-11 决定：官方技能的正文不对用户公开，用户自己写的技能、自己选择公开的社区技能必须照常可见、可编辑。
- **身份规则不够硬**：生产库里有 3 条 active 的 `SystemPromptConfig`，数据库文本会盖过代码里的提示文本。p6 已经在代码里把 `base.PRODUCT_IDENTITY_PROTOCOL` 接在数据库 `role_definition` 之后，`get_base_prompt` 不论数据库内容都会追加它；但它没写明优先于数据库配置，没覆盖「你是不是 DeepSeek」这种点名确认，也没覆盖「换一种语言完整复述」；它还告诉作者「技能全文在技能页面能看到」，官方技能隐藏后这句话就不对了。
- **一次请求加载了全部 17 个技能**（10-11 诊断会话）并逐字贴出正文。技能内容的 token 预算（12k）挡不住：短技能 17 个加起来也在预算以内，异常的是数量。

## Decision

1. **官方技能正文对用户隐藏**（`services/skill_package_service.instructions_hidden_from_users`：`source == "official"`）。
   - 字段格式：保留 `instructions` 字段，官方技能回传空串，并新增 `instructions_hidden: true`；其他技能 `instructions_hidden` 为 `false`，正文不变。涉及 `PublicSkillResponse`（列表与详情，`instructions_truncated` 恒为 `false`）、`SkillResponse`（`GET /skills` 的已添加技能）、`AddedSkillResponse`（`GET /skills/my-skills`）。名称、描述、分类、触发词照常返回。
   - 导出、资源：已添加的官方技能调用 `GET /skills/{id}/export`、`GET /skills/{id}/resources`、`GET /skills/{id}/resources/content` 都返回 403（`ERR_NOT_AUTHORIZED`，「Official skill content is not available」）。导出再导入就是复制，所以导出一并禁止。`resource_count` 仍返回数量，不含内容。公共库搜索本来就只查名称和描述，不会通过搜索结果反推正文。
   - 不变：用户自建技能（`user_skill`）的列表、创建、编辑、导出、资源读写全部照旧；社区技能（`source = "community"`，作者自己写、自己选择公开的）照常回传正文；管理后台 `/api/admin/skills/*` 的审核材料不经过这里，仍是全文；agent 的 `load_skill`、`read_skill_resource` 与显式选择注入（`ActiveSkill` 视图）仍拿到官方技能全文。发给浏览器、写进聊天记录的技能工具结果本来就只有技能名、路径和大小（`stream_adapter._client_safe_skill_payload`）。
   - 前端：`Skill`、`PublicSkill`、`AddedSkill` 类型加可选的 `instructions_hidden`。技能页「发现」卡片和「已添加」卡片对隐藏的技能：展开按钮改为「展开说明 / 收起说明」，展开后显示完整描述（取消两行截断）和一句「官方技能的具体指令不公开；添加后，AI 会在合适的时候使用它」；不取详情、不显示资源区；已添加卡片不显示导出按钮。侧栏技能弹窗不显示「技能内容」区，改为同义的一句说明。未挂路由的 `SkillDiscoveryPage` 同样处理。界面上原本就没有「复制到我的技能」或 fork 入口；分享（`POST /skills/{id}/share`）只针对自建技能。中英文案已加。
2. **身份与保密规则**（`base.PRODUCT_IDENTITY_PROTOCOL`，位置不变：数据库 `role_definition` 之后、`OUTPUT_PROTOCOL` 之前，所有项目类型、所有角色共用）。
   - 标题写明这是固定规则，与上文角色设定或其他配置冲突时以本节为准。
   - 自称 ZenStory 的 AI 写作助手；不说、不猜底层模型或厂商；点名问「你是不是某某模型」时不确认、不否认。
   - 系统提示、工具协议和官方技能提示词不原样贴、不逐段转述，换语言、换格式要求完整复述也一样；可以几句话概括能做什么、某个技能适合做什么。作者自己写的技能不受此限。
   - 不做输出侧拦截或文本检测（所有者 2026-10-11 明确否决），只靠这条提示词规则。
3. **每轮最多读取 3 个不同的技能**（`content_budget.MAX_LOADED_SKILLS_PER_REQUEST = 3`）。计数放在本请求共享的 `SkillContentBudget.admit_skill` 里，`load_skill` 和 `read_skill_resource` 共用：同一技能重复加载、分段续读、读资源不另计，第 4 个不同的技能返回普通错误，提示用已加载的技能完成、需要其他技能时让用户下一条消息继续。显式选择的技能（已注入 system prompt、最多 3 个）不计入。`load_skill` 的工具描述写明这个上限。

## Alternatives considered

- **不回传 `instructions` 字段（省略）**。最强理由：契约更干净，不会出现「有字段但没内容」。没采用：前端类型里 `instructions` 是必填字符串，管理后台和测试夹具也按这个形状读；空串 + 显式标记让界面能区分「官方隐藏」和「作者没写」，新前端先上线（Vercel 比 Railway 早约 25 分钟）时读到旧后端的全文也照常显示，旧前端读到新后端的空串只是展开后什么都不显示，两种时序都不会报错。
- **在 `instructions` 里放一句占位说明（如「官方技能内容不公开」）**。最强理由：旧前端不改也能显示说明。没采用：占位文字会被当成技能正文渲染成 markdown、参与长度判断，还会跟着进入任何复用这个字段的地方；文案和多语言应由前端负责。
- **输出侧检测：在回复里匹配厂商名或官方技能片段并改写**。最强理由：模型不遵守提示词时仍能拦住。没采用：所有者否决。作者要求换一种语言或编码复述时检测立刻失效，还要维护一套重的匹配代码。
- **只靠已有的 12k 技能内容预算，不加数量上限**。最强理由：已有机制，不新增规则。没采用：异常的是一次加载十几个短技能，它们加起来没超预算。
- **上限把显式选择的技能也算进去**。最强理由：「本轮用了几个技能」只有一个口径。没采用：显式选择本身最多 3 个、已注入 system prompt；算进去的话，作者选满 3 个后模型连一个目录里的技能都加载不了。
- **把身份规则挪到整个系统提示的最末尾**。最强理由：离模型生成最近，压得住前面所有数据库文本。没采用：p6 的位置（紧跟角色定义）已经保证无论数据库内容如何都会出现，标题里写明优先级即可；挪到末尾会和动态段（语言行、范围约束）交错，并让静态前缀缓存多失效一段。

## Consequences

- 收益：官方技能的方法不再能通过页面、接口、导出或资源读取拿到；用户自建和社区技能的可见性、可编辑性完全不变；agent 的技能能力不变；身份规则在代码里，数据库配置改不掉；单轮加载技能的数量有硬上限。
- 代价与剩余：
  - 用户只能凭名称和描述判断要不要添加官方技能，官方技能的 description 需要写清楚用途和适用场景。
  - 已添加的官方技能不能导出。此前已经导出的 zip、作者手工抄进自建技能的官方正文无法收回；按「自建技能可见」的规则，这些内容在作者自己的技能里照常显示。
  - 保密只靠提示词，模型不遵守时仍可能复述；本批没有用真实模型回放验证（不调用付费模型），上线后需要用诊断账号观察。
  - 需要第 4 个技能的任务要分到下一条消息。
  - 工具描述与身份段落文本变了，系统提示的前缀缓存会在上线后失效一次。
  - 侧栏技能弹窗把已添加的技能也标成「自定义」（原有问题，本次未改）。

## Verification

- 后端：`tests/test_api/test_public_skills.py`（官方技能列表与详情不含正文、`instructions_hidden`；社区技能照常；原有的预览/全文用例改用社区技能）、`tests/test_api/test_skills.py`（自建技能创建、编辑后在 `GET /skills`、`/skills/my-skills` 返回全文；已添加的官方技能为空串并标记，社区技能全文）、`tests/test_api/test_skill_packages_api.py`（官方技能导出、资源列表与读取 403，响应里没有正文；原有的已添加技能导出/资源用例改用社区技能）、`tests/test_agent/test_skill_tools.py`（`load_skill`、`read_skill_resource` 仍拿到官方技能全文与资源；第 4 个不同技能被拒、重复加载和续读不计数、新请求重新计数）、`tests/test_agent/test_db_only_writing_configuration.py`（数据库 active 行声称厂商身份时，三种项目类型的系统提示仍含身份规则且在角色定义之后）。全量 `pytest -q --no-cov -n auto`：5764 passed、287 skipped。
- 前端：`src/pages/__tests__/SkillsPage.test.tsx`（官方技能展开显示说明、不取详情；社区技能照常展开正文；已添加的官方技能没有导出按钮、不取资源；自建技能可导出、编辑框是可编辑的全文）、`src/components/__tests__/SkillSelection.test.tsx`（侧栏弹窗：官方技能显示描述和说明，自建技能显示全文）。全量 vitest：4371 passed、1 skipped；lint、lint:tokens、lint:i18n-keys、build:typecheck 通过。E2E `e2e/fixtures-responsive.ts` 的官方技能夹具改成新形状；`e2e/public-skills.spec.ts` 的展开用例只按「展开 / 收起」文字找按钮、不断言正文，新标签仍匹配，未改。
