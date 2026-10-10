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

## 依赖修复与复扫

用户已授权依赖元数据扫描和修复版本下载。扫描仅发送包名称与版本，不发送源码、业务数据、密码或 API Key。

| 依赖 | 原版本 | 修复版本 |
| --- | --- | --- |
| FastAPI / Starlette | 0.115.12 / 0.46.2 | 0.143.0 / 1.7.0（显式固定 Starlette） |
| PyJWT | 2.10.1 | 2.15.1 |
| cryptography | 44.0.3 | 50.0.2 |
| Axios | 1.9.0 | 1.20.0 |
| Vite | 6.3.5 | 6.4.4 |
| Vue / server-renderer | 3.5.13 | 3.5.43 |
| Element Plus | 2.9.9 | 2.14.7 |
| ECharts | 5.6.0 | 6.1.0 |

- 初次 OSV 扫描发现 Starlette、PyJWT、cryptography 命中公告；公告存在别名重叠，不将 GHSA/PYSEC 数量直接当作独立漏洞数。
- 初次 npm audit：6 个受影响包（4 high、2 moderate）；升级后包括开发依赖在内为 0。
- 新镜像中 48 个已安装 Python 包的 OSV querybatch 复扫没有返回已知漏洞；pip check 通过。
- 已同步更新 frontend/package-lock.json。ECharts 跨主版本更新通过类型检查和生产构建。
- 部分公告针对本项目没有使用的 JWKS、Node adapter、Windows StaticFiles 或开发服务器功能；扫描命中不等同于生产中均可利用。

## 剩余范围与风险

- 当前访问地址使用 HTTP，登录和 API 通信没有传输加密。需要域名/证书或指定 TLS 终止方式。
- 本次扫描覆盖 Python/npm 依赖，未完成宿主机和 Debian 系统包的完整 CVE 扫描；不能据此声称全部系统组件不存在漏洞。
- 历史离线部署包包含旧镜像，未重新构建，不能视为本次安全修复包。
- 保留 v1.0.5 版本号及既有标签，安全修复作为 main 后续提交。

## 验证与部署

- 后端：升级后 43 项测试，40 通过、3 个 PostgreSQL 集成测试跳过。
- 前端：vue-tsc、Vite 生产构建通过，6 项附件测试通过；构建提示大 chunk，未出现构建失败。
- HTTP 隔离验收：升级后 8 个匿名访问拒绝、8 个普通用户管理接口拒绝，畸形 Host 下敏感 API 仍返回 `Cache-Control: no-store`。
- 代码中未发现 `v-html`/`innerHTML` 输出模型内容；会话令牌不持久化到 localStorage；未发现追踪源码中存在实际管理员密码、API Key 或私钥的匹配。
- 上线前保存数据库转储、停机一致性数据备份及可回滚容器；不更改用户密码、模型供应商配置及业务数据。

- 新镜像已部署到 192.168.31.97:18080，容器健康检查通过，线上 OpenAPI 版本保持 1.0.5。
- 浏览器验收：对话测试、概览、用量统计、系统设置正常加载；概览和统计图表显示正常，未捕获浏览器 error。
- 本次依赖部署回滚备份：`/opt/AIGateway/backups/before-security-deps-20261010T072228Z`；数据库转储校验及停机一致性数据备份已完成。

## 公开公告

- [Starlette Host 校验漏洞 GHSA-86qp-5c8j-p5mr](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr)
- [Starlette 请求路径污染 authority GHSA-jp82-jpqv-5vv3](https://github.com/Kludex/starlette/security/advisories/GHSA-jp82-jpqv-5vv3)
- [Axios fetch adapter 原型污染 GHSA-vh66-26gq-q6x8](https://github.com/axios/axios/security/advisories/GHSA-vh66-26gq-q6x8)
- [Vite Windows 文件拒绝规则绕过 GHSA-fx2h-pf6j-xcff](https://github.com/vitejs/vite/security/advisories/GHSA-fx2h-pf6j-xcff)
- [Vite HTML 文件访问边界 GHSA-jqfw-vq24-v9c3](https://github.com/vitejs/vite/security/advisories/GHSA-jqfw-vq24-v9c3)
