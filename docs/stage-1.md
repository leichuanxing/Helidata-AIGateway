# 阶段 1：基础工程与单容器运行环境

验收日期：2026-10-04（Asia/Shanghai）。结果：通过。

## 修改文件清单

- 基础：`.gitignore`、`.dockerignore`、`README.md`。
- 后端：`backend/requirements.txt`，app 各包 `__init__.py`，`app/main.py`，`app/core/config.py`、`database.py`、`redis.py`，`app/api/health.py`，`app/models/user.py`，`app/services/bootstrap.py`、`provision_database.py`。
- Migration：`backend/alembic.ini`，`backend/alembic/env.py`、`script.py.mako`、`versions/0001_bootstrap.py`。
- 前端：`frontend/package.json`、`package-lock.json`、`tsconfig.json`、`vite.config.ts`、`index.html`、`src/main.ts`、`src/App.vue`。
- 部署：`docker/Dockerfile`、`entrypoint.sh`、`nginx.conf`、`redis.conf`、`supervisord.conf`，`config/config.yaml.example`。
- 验收：`tests/stage1_acceptance.py`、本文及 `docs/current-status.md`。

## 数据库及联动

Migration 0001 创建最小 users 表；启动自动升级后在事务中检查并创建 admin，重启不覆盖密码或安全状态。用户表将在后续正式 Migration 中兼容扩展。配置第一次生成随机密钥，后续读取持久化文件。前端通过 Nginx 调用 /api/health/detail，数据来自实际数据库/Redis/磁盘探测。

## 已执行的测试

| 验收 | 结果 |
| --- | --- |
| Python compileall | 通过 |
| Vue TypeScript 检查及生产构建 | 通过 |
| Docker 多阶段构建 | 通过 |
| Nginx 首页/API 代理 | 通过 |
| /health 与 /health/detail | 通过，全部服务 ok |
| 全新配置、数据库与管理员初始化 | 通过，UTF8，随机密码日志输出 |
| Alembic 当前版本 0001 | 通过 |
| 管理员 Argon2id、must_change_password | 通过 |
| 六个持久化目录与配置权限 | 通过 |
| PostgreSQL/Redis 不映射宿主机 | 通过 |
| 容器重启保留数据 | 通过 |
| 删除容器并重新挂载 /data 保留数据 | 通过 |
| 强制终止 Redis 后自动恢复 | 通过 |
| 强制终止 PostgreSQL 后自动恢复 | 通过 |
| 强制终止 Uvicorn 后自动恢复 | 通过 |
| 强制终止 Nginx 后自动恢复 | 通过 |
| 浏览器首页与刷新检查 | 通过，显示四项正常 |

部署端验收记录：`/opt/AIGateway/acceptance-stage1.log`。第一次验收脚本因精简镜像无独立 kill 可执行文件失败，已改用 shell 内建 kill，并重新完整执行通过。

## 已知限制与后续

阶段 2 的完整基础表和配置管理尚未实现，阶段 3 的认证与强制改密尚未实现。/v1 业务接口尚未实现。443 尚未启用 TLS。部署使用 18080，避免占用原有 80 端口。

首次启动时发现默认 SQL_ASCII 与继承 root HOME 的连接问题，均已修复并重新验证。初始数据使用非破坏方式迁移到 UTF-8，原数据库和 SQL 备份均保留。重建测试保留用户名、密码 Hash、安全状态及配置 Hash 完全一致。初始密码的旧 Docker 日志随验收删除的容器消失，阶段 3 增加管理员密码安全重置流程。

下一阶段为阶段 2：数据库与配置中心。
