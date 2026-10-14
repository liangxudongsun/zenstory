# App 文档接受带尾斜杠的共享地址

## Problem

预发布 App 的 `/docs/user-guide/editor/` 显示 Document Not Found，而文档首页的无尾斜杠链接正常。React 的 `/docs/*` 已接收这个地址，但 DocsPage 保留 slug 末尾斜杠，查找了不存在的 `editor/.md`。相对 Markdown 链接也会误把叶文档当作目录，分类导航的精确匹配同样不接受尾斜杠。

依据 [保留工作台内文档](../simplification/2026-10-13-retain-app-docs-reader.md)，App 阅读器与组织站静态文档共用内容，均应接受共享文档地址。

## Decision

只在 DocsPage 内复用一个路径规范化函数，去掉末尾斜杠后再解析 slug、相对目录、导航项和内部链接。保留 `.md` 兼容、查询参数、锚点、中英文内容选择与已有加载失败区分；不新增文档、重定向或 UI。

静态生成器不经过 React slug 解析，原本就输出 `docs/.../editor/index.html` 并规范化相对链接，canonical 仍为组织站无尾斜杠地址。生成器、Vercel 规则及现有 canonical 策略不修改。

## Alternatives considered

- **Vercel 全局去尾斜杠。** 能让部署后的地址统一，但本地 App 仍保留错误解析，也会改变其他路径的行为。修复实际文档解析足够。
- **只修叶文档的 slug。** 改动最少，但从同一共享地址继续点相对链接仍会落到错误目录，分类链接也仍不匹配；三处共用同一规范化即可一起保留既有文档导航语义。

## Consequences

同一文档的有尾、无尾斜杠入口均可读，内部链接继续使用既有无尾斜杠路由。实际不存在的文档和 Markdown 下载失败仍显示各自错误。公开文档地址、内容、样式及 canonical 策略保持不变。

## Verification

先补中英文真实 Markdown 加载及路径解析回归，原实现三项失败；修后 DocsPage、docsNavigation、site-domain 与 SEOProvider 四组 27 项通过。静态生成文档与 App/组织站域名隔离两项检查通过；ESLint、TypeScript 与完整前端构建通过。既有 320/390/768 文档抽屉浏览器回归改用尾斜杠入口，正文、键盘焦点、搜索和关闭三项通过，运行器正常退出 0。没有后端、云端或模型操作。
