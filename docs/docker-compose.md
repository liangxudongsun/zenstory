# Docker Compose 启动与自托管

仓库提供两套 Compose：`docker-compose.yml` 用于本机快速体验，`docker-compose.full.yml` 用于 PostgreSQL 和 Redis 的完整自托管部署。托管站点的 Railway/Vercel 发布另见[发布流程](ops/release-ci-cd.md)。

## 本机快速启动

需要 Docker Compose。配置仓库根目录 `.env`，填写自己的模型 Key，并设置固定的随机 JWT 密钥：

```dotenv
DEEPSEEK_API_KEY=填写自己的Key
JWT_SECRET_KEY=填写至少32字符的随机密钥
```

写作服务当前使用 `deepseek-flash`。使用真实 Key 生成文字会产生模型费用；开发验证使用 mock。仅启动页面不会替你配置项目写作提示词。

```sh
docker compose up -d --build
docker compose ps
```

默认访问 Web `http://localhost:5173`、API `http://localhost:8000`，API 健康入口是 `/health`。

## 创建管理员与写作配置

准备邮箱、唯一用户名和至少 12 字符的密码，以环境变量传给脚本，避免把真实密码写进命令历史：

```sh
export ZENSTORY_ADMIN_EMAIL=you@example.com
export ZENSTORY_ADMIN_USERNAME=admin
read -r -s ZENSTORY_ADMIN_PASSWORD
export ZENSTORY_ADMIN_PASSWORD
docker compose exec -e ZENSTORY_ADMIN_EMAIL -e ZENSTORY_ADMIN_USERNAME \
  -e ZENSTORY_ADMIN_PASSWORD server python scripts/create_admin.py
unset ZENSTORY_ADMIN_PASSWORD
```

管理员账号不需要邀请码和邮箱验证。不要把此脚本当作普通用户注册入口。

在管理后台维护 novel、short、screenplay 的系统提示词，保存后重新加载。新数据库缺少启用的对应配置时，写作会明确报错。官方技能从数据库读取，没有源码默认技能或自动种子。维护方法见[写作配置](agent-writing-guidance.md)。

创建账号后默认使用免费权益：每天 10 条 AI 消息、3 个项目。按需运行 `scripts/seed_subscription_plans.py` 初始化套餐，再从后台给账号开通权益。

## 普通用户注册

默认注册需要邀请码。管理员从邀请页面生成后交给用户；可选邀请策略由 `AUTH_REGISTER_INVITE_CODE_OPTIONAL` 与前端注册配置控制。

邮箱验证和密码重设需要 Redis、`RESEND_API_KEY`、有效的 `RESEND_FROM_EMAIL`。快速 Compose 没有 Redis，不适合直接开放邮箱注册。先完成邮件和 Redis 配置，再让普通用户注册。

## 完整部署

复制环境模板并填齐所有必填值：

```sh
cp apps/server/.env.docker.example apps/server/.env.docker
cp apps/web/.env.docker.example apps/web/.env.docker
```

后端模板包括独立的 PostgreSQL owner/app 用户、数据库名、对应密码、Redis 密码、JWT 密钥和模型 Key。使用 URL 安全的随机密码，owner 与 app 凭证分开。Web 模板的 `VITE_API_BASE_URL` 是浏览器可访问的 API origin，不加 `/api/v1`。

Compose 的变量替换不会仅凭 `env_file` 读取所有值，启动前需导出两个文件：

```sh
set -a
. apps/server/.env.docker
. apps/web/.env.docker
set +a
docker compose -f docker-compose.full.yml config --quiet
docker compose -f docker-compose.full.yml up -d --build
```

完整部署默认只在本机绑定 Web `127.0.0.1:8080`、API `127.0.0.1:8000`；数据库和 Redis 不暴露宿主端口。对外服务先配置 TLS 反向代理与准确的 `CORS_ORIGINS`、`FRONTEND_URL`。

`postgres-init` 初始化 app 角色；名为 `migrate` 的服务当前调用 `init_db` 创建缺失表，**不会替已有数据库执行 Alembic 列迁移**。升级前核对待执行迁移、备份与回滚兼容性，不把容器健康当成 schema 已更新。

## 可选能力

| 能力 | 配置入口 |
| --- | --- |
| 邮件验证、密码重设 | Redis、Resend 配置 |
| Google 登录 | 后端 OAuth 配置、准确回调域名、前端 Google 开关 |
| 语音 | 腾讯云语音凭证 |
| 素材拆解 | Prefect server、worker、任务注册及模型配置 |
| 在线支付 | Zpay 配置与显式启用，核对回调及权益发放 |
| 兑换码 | 套餐初始化与独立 HMAC 密钥 |
| 外部 Agent / CLI | API HTTPS origin、用户 API Key，见 `apps/cli` |

灵感库默认关闭。自托管需要时，后端与前端的开关必须一致；配置方式以 Compose 与环境模板为准。面向在线用户的文档只显示“待开放”。

## 数据与排查

快速部署的 SQLite、完整部署的 PostgreSQL/Redis 和上传文件使用命名卷。停止或重建容器通常保留卷；删除卷会删除数据，清理前先核对用途和备份。

```sh
docker compose logs --tail=100 server
docker compose ps
curl -f http://localhost:8000/health
```

端口可通过 `SERVER_PORT`、`WEB_PORT` 调整。前端实际 origin 必须加入 CORS；不要把数据库、Redis 或生产凭证暴露到浏览器环境变量。

升级涉及 worker 时，先排空任务。托管环境的生产操作、卷保留与 tag 门禁遵循[发布流程](ops/release-ci-cd.md)。
