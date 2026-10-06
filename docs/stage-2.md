# 阶段 2：数据库与配置中心

日期：2026-10-04（Asia/Shanghai）。结果：验收通过。

## 完成内容与文件清单

- `backend/alembic/versions/0002_foundation.py`：兼容基础表迁移与种子数据。
- `backend/app/models/user.py`：users、roles、user_groups、system_settings、audit_logs 模型与约束。
- `backend/app/core/config.py`：六节配置类型、范围、端口冲突校验、错误脱敏及兼容默认值。
- `backend/app/core/database.py`：异步连接池、超时、参数脱敏和 Session 依赖。
- `backend/app/core/redis.py`：统一异步 Redis 客户端及连接参数。
- `backend/app/services/config_check.py`：容器 CLI 脱敏读取/校验配置。
- `backend/app/services/render_runtime.py`、`serve.py`：运行配置生成及按配置启动 API。
- `backend/app/services/bootstrap.py`、`provision_database.py`：适配角色关系与 SecretStr。
- `backend/alembic/env.py`：迁移连接超时和参数脱敏。
- `backend/app/main.py`、`api/health.py`：类型化日志参数，阶段版本和服务错误日志。
- `docker/Dockerfile`、`entrypoint.sh`、`supervisord.conf`：按配置生成并运行 Nginx/API/Redis。
- `config/config.yaml.example`：数据库连接池及 Redis 超时默认字段。
- `frontend/src/App.vue`：阶段标记更新为 2。
- `tests/test_config.py`、`test_migrations.py`、`stage2_acceptance.py`：配置、迁移和真实升级验收。
- `README.md`、`docs/current-status.md`、本文：文档更新。

## Migration

0002 新建 roles、user_groups、system_settings、audit_logs。users 增加 role_id、user_group_id、姓名、邮箱、手机号、最后登录时间；旧 role 字段兼容保留，并与 role_id 通过组合外键验证一致性。

角色种子为 super_admin/admin/user。迁移保留旧数据中的其他角色代码，不擅自提升或降低已有权限。user_groups 初始为空，未自动赋予权限。system_settings 初始化系统名称、中文语言、Asia/Shanghai 时区。敏感进程配置仍在权限受限的 YAML 文件中，不存入系统设置表。

没有使用 create_all；没有删除业务数据库。升级前生成 SQL 备份。downgrade 只在临时测试数据库执行，原用户数据验证保留后重新升级。

## API、页面与联动

没有新增业务 API。原 /health、/health/detail 及 /api 别名保留，detail 的 phase 更新为 2。页面继续展示真实服务健康状态，不添加未认证的设置编辑页面。

配置检查通过 `docker exec helidata-ai-gateway python -m app.services.config_check` 完成，数据库密码和 JWT 密钥显示为星号。配置修改须重启整个容器；启动时重新读取并生成运行配置。Nginx/API 和 Redis 内部监听端口共同适配配置。非法配置拒绝启动，错误只显示字段位置，不能泄露用户输入值。

数据库角色、组及设置的后台管理页面属于后续阶段，审计表的业务写入与查询也在对应业务阶段实现。

## 测试及结果

| 测试 | 结果 |
| --- | --- |
| Python 编译、Vue TypeScript/Vite、Docker 构建 | 通过 |
| 真实 0001→0002 升级 | 通过，管理员与配置摘要完全一致 |
| 五张基础表及角色/设置种子 | 通过 |
| 临时库升级、降级、再升级 | 通过，UTF-8 用户与原密码 Hash 保留 |
| 非法配额、周期、并发、角色匹配及不存在的用户组 | 通过，数据库拒绝无效写入 |
| 配置单元测试五项 | 全部通过 |
| 配置不存在自动生成、重复启动不覆盖 | 通过 |
| YAML/字段/密钥长度/监听冲突校验 | 通过，错误不泄露测试密钥 |
| PostgreSQL 停止 | 返回 503，记录明确服务错误；恢复后健康 |
| Redis 停止 | 返回 503，记录明确服务错误；恢复后健康 |
| API=8010、Redis=6380、max_concurrency=123，重启读取 | 通过，Nginx/API/Redis 正常 |
| 恢复原配置并再次重启 | 通过，原数据与配置摘要一致 |
| 全新 /data 初始化 | 通过，0002、UTF8、管理员角色和首次改密标志正常 |

部署验收记录：`/opt/AIGateway/acceptance-stage2.log`。临时迁移测试库已自动删除，临时启动测试容器在验收后停止并移除，测试数据目录保留在已排除构建的 .deployment 中。系统仍仅用一个应用容器运行。

## 已知限制和下一阶段

配置采用启动时读取，尚未实现在线热更新。数据库内部地址固定为 127.0.0.1:5432；修改数据库密码需同步角色凭据。并发/队列/JWT 字段已校验，但业务执行仍由后续阶段实现。暂无登录、后台用户管理、设置页面、API Key 或真实模型调用；TLS 尚未配置。

下一阶段：阶段 3，登录、用户、角色与权限。
