# 数据库设计 · Migration0017

PostgreSQL15使用UTF-8，应用以非超级用户访问，运行在容器内127.0.0.1。pgvector0.8.7提供余弦向量检索。Alembic是唯一结构迁移入口；启动自动升级head。最终完整DDL见`database-schema.sql`，不包含业务数据或凭据。

| 数据域 | 表及关系 |
| --- | --- |
| 身份 | roles；users关联role和user_group，Argon2id密码、auth_version与软删除；refresh_sessions关联用户及撤销状态 |
| 授权 | user_groups、model_groups、user_group_model_groups、model_group_models；用户组授予模型组，模型组排序逻辑模型 |
| 接入 | api_keys关联用户，保存Key摘要/前后缀和状态；providers保存AES-GCM密文及配置版本；logical_models、provider_model_mappings建立逻辑/上游映射 |
| 调度/配额 | quota_reservations及相关累计状态；Redis维护带租约和TTL的四级并发/队列/会话粘性，数据库保留消费事实 |
| 调用 | call_logs，request_id唯一；标量身份ID及名称快照保留删除后的历史，trace为脱敏JSONB |
| 统计 | usage_hourly、usage_daily，bucket加用户/组/Key/Provider/请求模型/逻辑模型/协议/操作复合主键；累计分子和有效样本数用于加权平均 |
| 路由 | route_configs、route_samples、route_vectors、route_decisions；样本版本/向量代际/模型/维度必须一致，决策保存证据快照 |
| 合规 | sensitive_words、review_samples、review_vectors、compliance_policies、compliance_logs；本地384维向量，日志保存风险及版本快照 |
| 运维 | system_settings键/JSONB值/范围；audit_logs记录事件时身份快照；backups保存任务状态/文件SHA256/体积/时间，不在库内存备份包 |

历史标量ID/快照不会随业务对象软删除被改写。API Key仅存不可逆摘要；Provider密文依赖独立32字节Master Key，不依赖JWT签名密钥。库及配套Master Key备份必须一起保留。

调用日志写入和usage累计在同一数据库事务内，由唯一Request ID实现幂等。数据库失败时fsync到受限磁盘补偿，恢复后重放。Redis或进程崩溃不会使未知消费伪装为零；未上报预算保留并提供经审计的管理员显式调账。

0015增加备份任务及单活跃任务约束。0016增加Provider/Key/用户组/请求模型/逻辑模型与created_at、id的联合调用索引。0017增加可空request_body/response_body JSONB字段及operations设置行；旧历史记录为空，默认关闭正文采集。operations保存在同一次数据库备份中，包含品牌图片和设置revision。

0017降级删除新增正文列，因此已开启后保存的预览会丢失；generic operations设置行保留以便再升级。旧库升级不会重置用户凭据、Provider密文、Master Key或原有业务配置。0016索引在事务内创建，大表发布需维护窗口评估锁等待。最终旧0014→0017及降级/再升级的隔离验证见测试记录。

默认366天后分批清理call_logs、route_decisions、compliance_logs，每轮每表最多1000行。用量汇总和管理审计长期保留。调短保留策略不会删除当前活跃记录；配置最小366天覆盖最长统计窗口。资料和业务原始内容不得放入审计details或常规日志。
