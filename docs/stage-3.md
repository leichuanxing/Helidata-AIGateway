# 阶段 3：登录、用户、角色与权限

日期：2026-10-04（Asia/Shanghai）。阶段状态：已完成并通过验收。

## 完成内容和文件清单

- `backend/alembic/versions/0003_auth.py`：认证版本、软删除标记、Refresh 会话表和索引。
- `backend/app/models/user.py`：认证字段与 RefreshSession 模型。
- `backend/requirements.txt`：固定版本 PyJWT。
- `backend/app/core/security.py`：Argon2id、JWT、Token Hash、密码策略。
- `backend/app/core/dependencies.py`：逐请求用户/会话状态和角色检查。
- `backend/app/core/exceptions.py`、`main.py`：统一脱敏错误、Request ID、接口注册和无缓存响应。
- `backend/app/core/config.py`：刷新期限、失败限制、Cookie 配置。
- `backend/app/schemas/auth.py`：登录、改密、资料、创建/编辑和安全输出模型。
- `backend/app/services/sessions.py`、`reset_admin.py`：会话撤销、操作审计、root 恢复工具。
- `backend/app/api/auth/routes.py`：登录、刷新、退出、当前账号和修改密码。
- `backend/app/api/admin/users.py`：用户 CRUD、角色范围、密码重置和超级管理员保护。
- `backend/app/api/portal/profile.py`：个人资料局部编辑。
- `backend/app/api/health.py`：当前阶段更新为 3。
- `docker/nginx.conf`：保留原始 Host 端口，支持浏览器来源校验。
- `frontend/src/api/client.ts`、`stores/auth.ts`、`main.ts`：统一请求、自动刷新、内存 Token 和路由权限。
- `frontend/src/App.vue`、`Health.vue`：后台布局和原健康页。
- `frontend/src/views/Login.vue`、`Password.vue`、`Users.vue`、`UserDetail.vue`、`Profile.vue`、`Portal.vue`：登录、改密、列表、新增/编辑、详情、个人设置和用户中心入口。
- `tests/stage3_acceptance.py`：真实 PostgreSQL/Redis/HTTP 认证与权限验收。
- `README.md`、`docs/current-status.md`、本文和 `docs/stage3-users.jpg`：操作说明与界面验证记录。

## 数据库变更

0002→0003 增加 users.auth_version 和 deleted_at，并建立 refresh_sessions；旧用户 ID、用户名、Hash、角色、状态、首次改密状态和创建时间全部保留。升级前备份存放于 `/data/backup/stage3-before-upgrade.sql`。

Refresh Token、CSRF Token 只保存 Hash，Access Token 为签名 JWT。用户删除采用软删除，会话撤销与数据变更在同一事务完成。超级管理员变更使用事务锁，避免并发绕过最后一个超级管理员保护。测试只删除本轮自行创建的临时账号，未删除业务用户。

## 接口、前端与联动

API 清单见 README 阶段 3 表格。前端提供真实登录和用户管理表单，不使用 Mock API。用户详情展示真实账号资料，尚未实现的 Token 用量和 API Key 数量不伪造数值。

初次登录只允许当前账号查询、改密和退出。管理员默认进入用户管理；普通用户进入用户中心。Model 广场仅提供入口，模型和 Key 的真实数据在阶段 4–6 实现。

禁用账号、改密、重置、角色/用户组变化会递增认证版本并撤销 Refresh 会话；每次后台或个人请求都检查数据库当前状态。退出撤销当前会话，旧 JWT 同时失效。Refresh Cookie HttpOnly/SameSite，刷新和退出另有 CSRF/Origin 校验。JWT 不存入 localStorage。

API Key 尚未创建，不能在本阶段声称已测试 Key 调用失效；相应 Gateway 联动留给阶段 4/7/8。HTTPS 尚未配置，当前用于内网 HTTP 验收。

## 已执行测试

- 前端 vue-tsc、Vite、Docker 构建；Python 编译。
- 原用户数据摘要升级前后相同。
- 登录、首次强制改密、错误原密码、弱密码和同密码拒绝。
- 修改密码后旧 JWT 失效。
- Refresh 轮换、旧 Token 重放拒绝、CSRF 和外部来源拒绝、Hash 存储。
- 普通用户后台 API 拒绝、管理员不能查看/重置/删除管理员或超级管理员、不能创建高权限角色或提升角色。
- 自删除、自禁用拒绝。
- 创建、详情、搜索、资料修改、局部修改保留其他字段。
- 禁用后 Access/Refresh/登录拒绝；启用不能复活旧 Token。
- 管理员重置后撤销旧会话、强制改密；软删除后登录拒绝且历史用户行保留。
- 伪造和过期 JWT 拒绝，退出后会话失效。
- 五次失败后限制，12个同时失败请求仅5个参与验证，其余返回429。
- 登录/用户操作审计记录存在，不输出密码 Hash。
- 浏览器实际登录、列表、新增表单、详情、中文标签和退出验证；容器替换后 Refresh 会话能恢复。

曾遇到验收启动早于 Redis 就绪导致连接失败；测试调度已等待 /health 通过后运行。此项属于测试启动顺序修正，业务配置未变更。浏览器发现操作列显示不便，已固定右侧并重新验证。局部 PATCH 改为只应用提交字段，避免覆盖未提交资料。

## 后续

阶段 4：用户组、API Key 与模型权限。模型调用、统计和 Dashboard 按对应后续阶段实现。现阶段没有真实上游模型调用能力。

## 阶段 3 最终部署状态

镜像：`helidata-ai-gateway:stage3`，地址：`http://192.168.31.97:18080/login`。最终后端验收记录：`/opt/AIGateway/acceptance-stage3-delivery.log`。

现有 admin 已通过 root 恢复工具生成一次性临时密码，并验证登录成功且强制改密；未替用户设置正式密码。临时登录信息保存在被 Git 排除的 `.deployment/admin-stage3-login.txt`（服务器副本权限600），不写入源码或报告。实际业务数据只保留原 admin，所有验收账号已清理；操作审计仍保留。

界面截图中的账号为已清理的验收账号，截图仅用于展示真实界面验证结果。

新增 `tests/stage3_startup.py` 验证全新数据目录，包括宿主机目录0700的情况。初次测试发现该权限阻止服务用户进入 /data；`docker/entrypoint.sh` 已将挂载根目录设为0711，数据库子目录仍700，配置文件仍640，没有放宽密钥文件访问权限。首次初始化结果见最终记录。

严格目录权限下的全新启动验收已通过：随机管理员密码输出、登录成功、强制改密、迁移版本0003和目录权限均正常。记录：`/opt/AIGateway/acceptance-stage3-startup.log`。临时启动测试容器已清理。阶段 3 全部验收完成。
