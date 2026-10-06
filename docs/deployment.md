# 部署、备份与恢复

正式完整构建及首次启动见README。当前目标主机192.168.31.97，应用根目录/opt/AIGateway，宿主数据/data对应/opt/AIGateway/data，入口18080。现有OpenResty和Uptime Kuma使用其他端口，部署不修改这些服务。仅80映射容器端口，不开放PostgreSQL/Redis。

当前部署已于2026-10-06从0017升级0022，详见[正式18080更新](reproduction-production-0022.md)。下方stage20固定脚本及0017流程为历史发布记录；本次固定脚本为docker/deploy_reproduction_0022.py，不能重复使用。

## 发布与验证

1. 构建完整`docker/Dockerfile`并固定镜像ID。阶段Dockerfile仅用于候选迭代，交付使用完整构建。
2. 使用独立0700 UUID数据卷运行测试；不挂载生产卷、不使用生产Master Key、不执行真实付费推理。
3. 记录生产镜像、数据挂载、端口、数据库版本、Provider状态与业务/凭据摘要。确认窗口后停止入口及应用工作进程，等待在途调用结束。
4. 实际pg_dump custom备份，停止容器并制作完整冷态/data归档。备份目录0700、文件0600，包含密钥，不对外下载或上传。
5. 将旧容器停机保留，新容器挂同一/data、18080、unless-stopped运行。entrypoint自动Migration到0017。
6. 验证四进程RUNNING、health、pgvector、OpenAPI0.20.0、CSP、公开设置；比对账号/password/auth_version、Provider密文/业务配置、模型/组/Key、config和Master Key摘要。确认没有隔离测试用户进入生产。

`docker/deploy_stage20.py`是本次0014→0017的固定镜像发布脚本，默认只读检查，`--deploy`才执行。它固定旧/新image ID和Provider117，因此不能直接用于以后任意版本或其他服务器。检查失败不会继续覆盖；失败自动恢复对应冷态数据及旧镜像。发布记录包含受保护备份位置与旧停机容器名。

旧容器停机后仍引用同一/data，**不得直接启动它与新容器同时访问数据卷**。保留备份和旧镜像直至确认交付，清理需遵循管理员保留策略。

## 手动备份与离线恢复

后台备份是pg_dump custom + config + Master Key + uploads + manifest的tar.gz。使用受控账户下载，核对列表SHA256和体积，先检查成员均为普通文件、路径没有绝对路径或`..`。备份未加密；包含敏感配置，不进Git或交付包。

维护窗口停止网关写入，在受控临时目录解包，保持目录0700、文件0600。先在独立PostgreSQL临时数据库执行`pg_restore --no-owner --no-acl --exit-on-error`，核对alembic_version、users、providers和配套Master Key可解密性，再决定恢复生产。恢复目标角色需依据该实例的config创建，业务对象归属应用角色；pgvector扩展需具备安装权限。不要将测试恢复库直接暴露为生产。

确认正式恢复后停止容器，保留现有数据作为回退，恢复数据库至匹配实例及对应config/Master Key/uploads。若使用已有实例，需要明确目标数据库、清理方式、应用角色所有权；不可对运行中的库随意`--clean`。重新启动匹配镜像并校验健康和业务记录。Redis持久态包含会话/租约，不以手动备份声称跨Redis原子恢复；恢复后撤销遗留会话、清理过期租约并核对未上报配额。

品牌PNG和业务设置在数据库内，与pg_dump是同一快照；config/Master Key/uploads文件需停止相应写入。文件备份清单明确此边界，不承诺跨数据库、任意外部文件写入的原子快照。

## 精确回退

本次发布另保留停止后的整个/data冷归档，不依赖仅SQL转储。停止失败版本，将失败/data改名保留，再将冷归档按原UID/GID和权限恢复到原位置，恢复旧容器名称并启动旧固定镜像。核对原0014及凭据摘要。回退意味着放弃发布后新写入的业务数据；如果新版本已接受真实流量，应先备份失败卷并制定增量补偿，不能静默覆盖。

Migration0017可降级，但会删除新正文预览列；0016索引创建也需要评估生产日志体积和锁等待。旧数据卷已通过隔离升级/降级验证，这不替代发布前的实际生产备份。

## 运维检查

```bash
docker inspect --format '{{.State.Health.Status}}' helidata-ai-gateway
docker exec helidata-ai-gateway supervisorctl status
curl -fsS http://127.0.0.1:18080/health/detail
docker exec helidata-ai-gateway alembic current
```

不要贴出完整docker logs、config.yaml、Provider密文或备份内容。通过Request ID、固定错误码、池容量和依赖状态定位。日志索引、默认500执行槽和短时1000客户端压力结果不是供应商并发能力承诺。监控磁盘、队列、补偿积压和备份可恢复性；避免仅检查HTTP200。
