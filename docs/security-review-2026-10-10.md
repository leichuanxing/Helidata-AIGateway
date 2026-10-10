# 安全检查记录（2026-10-10）

本次为 v1.0.5 后续安全修复。检查范围：网页会话与 API Key 鉴权、角色权限、输入与文件校验、数据库查询、日志脱敏、备份、首次部署及应用容器配置。未执行破坏性攻击，也未调用付费模型。检查结果不能证明系统不存在其他漏洞。

## 已修复

| 问题 | 修复 | 验证 |
| --- | --- | --- |
| 安全行为使用 `request.url.path`，旧 Starlette 允许畸形 Host 污染该路径 | 使用 ASGI `scope['path']` 判断网页会话、协议错误格式、缓存及失败日志行为 | 畸形 Host 不再改变网页会话/API Key 鉴权分支；管理接口无登录拒绝访问 |
| 自定义脱敏规则的超时可在多个字段上累积，且原先在鉴权前执行 | 每份日志预览设置 50 ms 总预算；超时隐藏内容；通过身份和用户组检查后才运行脱敏 | 未认证请求不执行脱敏，超时内容隐藏，正常令牌脱敏保留 |
| 修改密码的原密码校验缺少失败限流 | 按账号使用原子 Redis 限流，复用登录失败次数和锁定时间配置；失败审计；Redis 故障时拒绝校验 | 限流/故障时不执行 Argon2，错误原密码不修改凭据，成功改密继续撤销会话 |
| 源码首次部署将随机管理员密码输出到容器日志 | 密码改写入 `/data/config/initial-admin-password.txt`，权限 600，独占创建并禁止跟随符号链接；事务失败清理；日志只输出查看指引 | 文件权限及禁止覆盖测试；README 更新查看与删除指引 |
| 开发服务器默认监听全部网卡 | `npm run dev` 默认绑定 `127.0.0.1` | 检查 package.json；需要远程开发时由操作者明确指定监听地址 |

## 尚需处理

在线扫描和依赖下载安装被自动审批阻止，原因是向 npm/OSV/PyPI 发送依赖名称与版本的第三方披露尚未获得明确授权。已向用户请求授权；依赖文件没有假装更新，线上仍使用原依赖。

- Starlette 0.46.2 受 Host/path 重构公告影响。代码层面已隔离安全判断；库升级仍待完成。候选：FastAPI 0.143.0 + Starlette 1.7.0，安装后须执行兼容与回归验证。
- Axios 1.9.0 存在后续修复公告；部分问题只影响 Node 适配器，本项目在浏览器运行，不能将所有公告等同于可利用的生产漏洞。候选：1.20.0，待安装、完整扫描与前端构建。
- Vite 6.3.5 存在开发服务器文件访问边界漏洞。生产使用 Nginx 静态资源，不运行 Vite 开发服务器；已收紧开发监听地址，依赖仍需升级至受维护的修复版本（候选 6.4.4）。
- cryptography 44.0.3 需继续核对后续安全公告及轮子内 OpenSSL；候选 50.0.2 仅为待验证升级目标，尚未安装。
- 当前访问地址使用 HTTP，登录和 API 通信没有传输加密。需要提供域名/证书或指定 TLS 终止方式；本次没有改变现有访问端口和客户端协议。
- 未对服务器上其他应用、SSH 凭据或其他开放端口进行修改。历史离线包包含旧版本镜像，不能视为本次安全修复包。

## 验证与部署

- 后端：43 项测试，40 通过、3 个 PostgreSQL 集成测试跳过。
- HTTP 隔离验收：9 个匿名访问拒绝、8 个普通用户管理接口拒绝，畸形 Host 下敏感 API 仍返回 `Cache-Control: no-store`。
- 代码中未发现 `v-html`/`innerHTML` 输出模型内容；会话令牌不持久化到 localStorage；未发现追踪源码中存在实际管理员密码、API Key 或私钥的匹配。
- 上线前保存数据库转储、停机一致性数据备份及可回滚容器；不更改用户密码、模型供应商配置及业务数据。

## 公开公告

- [Starlette Host 校验漏洞 GHSA-86qp-5c8j-p5mr](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr)
- [Starlette 请求路径污染 authority GHSA-jp82-jpqv-5vv3](https://github.com/Kludex/starlette/security/advisories/GHSA-jp82-jpqv-5vv3)
- [Axios fetch adapter 原型污染 GHSA-vh66-26gq-q6x8](https://github.com/axios/axios/security/advisories/GHSA-vh66-26gq-q6x8)
- [Vite Windows 文件拒绝规则绕过 GHSA-fx2h-pf6j-xcff](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff)
- [Vite HTML 文件访问边界 GHSA-jqfw-vq24-v9c3](https://github.com/vitejs/vite/security/advisories/GHSA-jqfw-vq24-v9c3)
