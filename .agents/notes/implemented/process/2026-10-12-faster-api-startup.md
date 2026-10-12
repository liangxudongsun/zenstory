# 删除阻塞启动的向量维护入口

## Problem

用户在本轮明确撤回无损发布要求，改为缩短发布切换。API 依赖 LlamaIndex/Chroma，且启动包装器能在启动 Uvicorn 前跑索引维护，增加依赖和启动负担。

## Decision

随完整索引栈删除依赖与启动维护入口，start_api 直接 exec Uvicorn。保留已有 worker 数量、readiness 与 drain 窗口。部署说明写明实际挂载：生产 `server-volume` 仍在 /app/chroma_data（反馈截图经 FEEDBACK_UPLOAD_DIR 写在其下，另有素材原文件），staging 在 /app/uploads；保留素材原文件与截图，不 detach、压缩或删除原卷，也不改挂载路径。只提交当前 PR，不新增发布生产者、不部署生产。

## Alternatives considered

- 实现无损/静默窗口：能保护在途连接，但用户已明确撤回此要求，停止实现。
- 缩短 graceful 或跳过 readiness：可能更快，但会截断任务或把未就绪实例接入；不采用。

## Consequences

依赖和启动工作减少；实际切换时间仍依赖镜像构建、数据库和 provider 调度，不能从代码删减推断固定提速秒数。
