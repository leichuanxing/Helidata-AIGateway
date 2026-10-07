# 部署、备份与恢复

正式完整构建及首次启动见README。当前目标主机192.168.31.97，应用根目录/opt/AIGateway，宿主数据/data对应/opt/AIGateway/data，入口18080。现有OpenResty和Uptime Kuma使用其他端口，部署不修改这些服务。仅80映射容器端口，不开放PostgreSQL/Redis。

当前应用v1.0.1，数据库0031。历史阶段发布和测试工具已清理；日常完整构建使用docker/Dockerfile。

## 发布与验证

1. 构建完整镜像并固定镜像ID，在独立数据目录验证，不使用生产密钥。
2. 记录生产镜像、挂载、端口、数据库版本及配置。维护窗口先停止入口及应用写入。
3. 使用pg_dump custom备份数据库，停止容器后制作冷态/data归档。备份目录0700、文件0600，包含密钥，不进入Git。
4. 新容器挂载相同/data和18080，以unless-stopped运行。启动自动执行迁移到0029。
5. 检查四进程、health、数据库版本、Provider和业务配置，确认配置和Master Key匹配。

最近一次正式发布的备份和旧镜像按管理员保留策略维护；历史开发备份和隔离测试数据可清理。旧容器与新容器不能同时访问同一/data。回退必须配套恢复相应备份及配置，不能只启动旧镜像。

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
