# Agent Note: SSO 完成时核对浏览器仍停留在原登录入口

## Problem

PublicRoute 用 effect cleanup 的 `active=false` 取消旧 SSO 校验。实际 App 的 Routes 置于 Suspense 内，目标页面按需加载；浏览器地址先变为目标页，尚未加载的路由可以使旧子树继续保留，passive effect cleanup 尚未执行。此时旧校验成功，仍会携带已验证 token 跳向原来的 SSO 目标，打断作者已经选择的导航。

已有“离开登录页后不跳转”测试依赖目标模块加载时机，单独运行通过不足以排除这个窗口。控制 PrivacyPolicy 实际模块加载的真实 App 回归在旧实现中确定复现：浏览器已经是 `/privacy-policy`、目标页面仍等待导入，旧校验成功写出一次外部跳转。

## Decision

复用 effect 已捕获的路由 pathname/search，和 `window.location` 当前 pathname/search 一起检查完成归属。`active` 仍保留；开始校验、消费校验结果及异常/失败状态收尾均须仍处于同一入口。浏览器已离开时不跳转、不由旧 caller 更新失败界面，不等待 React 清理旧树。

既有会话代次、refresh lineage、账号替换隔离、允许的跳转域和 token 验证保持不变。hash 不参与 SSO 目标参数；没有新状态、持久字段、监听器、延时或重试。

回归仅控制目标页面的动态导入和已有 HTTP 边界；使用真实 App、BrowserRouter、PublicRoute、认证及 SSO 实现。目标导入仍挂起时验证不跳转，随后放开实际页面并再次验证地址与认证保留。原有健康 SSO、strict、退出、换号和 refresh 控制继续断言。

既有 route guard 单元测试使用 MemoryRouter 适配器；其初始浏览器地址同步到同一个测试入口，使 SSO 的真实导航边界与适配器路由一致，保留全部原断言。

## Alternatives considered

- **仅等待旧测试中的新页面标题再断言**：能减少测试调度波动，但覆盖不到用户正在等新页面加载的真实窗口，因此保留原断言并增加可控的挂起场景。
- **把整个 SSO effect 改成 layout effect 或增加 popstate 取消监听**：可更早接收到部分离开信号；但会改变副作用执行时机或增加监听生命周期。完成时核对当前浏览器地址直接表达导航归属，现有 active 清理继续负责已卸载实例。
- **延时等待 cleanup 或重跑测试**：实现简单；无法保证更慢的懒加载时序，也会拖慢正常导航，不采用。

## Consequences

用户离开登录入口后，较晚完成的校验不会再抢走导航。相同入口上的正常 SSO 行为和会话归属控制不变。已发出的只读 token 校验不会因路由离开而额外取消或重试；仅忽略其不再拥有导航权的 caller 结果。
