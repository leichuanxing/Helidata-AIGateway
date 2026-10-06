# 阶段 13：Token、TTFT、Tokens/s 与用量统计

2026-10-05（Asia/Shanghai）。部署镜像 `helidata-ai-gateway:stage13`，应用 `0.13.0`，迁移 `0010`。访问 http://192.168.31.97:18080。阶段14 Dashboard、排行榜及后续协议扩展尚未实现。

## 指标口径

| 指标 | 实际采集口径 |
| --- | --- |
| Input / Output / Cached / Total | 使用有效上游 usage：prompt_tokens / completion_tokens / prompt_tokens_details.cached_tokens / total_tokens。缺失字段保持 NULL，不估算、不把配额预留视为消耗。 |
| usage_status | 基础输入、输出、总 Token 均已上报时 available，否则 usage_unavailable；缓存字段单独统计有效样本。 |
| 流式 TTFT | HTTP 中间件收到请求到首个有效内容、推理内容、拒绝内容或工具调用增量，毫秒；包含校验、排队和故障转移。心跳、role-only、usage-only、finish-only 不计作首个内容。 |
| 非流式 TTFT | NULL。整包 JSON 不能观测真实首 Token；Excel 允许非流式 TTFT 为空。 |
| 流式生成时长 | 首个有效内容到收到 DONE；错误或取消时到流终止。未观测有效内容时不可用。 |
| 非流式生成时长 | 最终成功上游尝试从发起到有效整包响应；包含网络等待，不能解释为供应商纯解码速度。 |
| Tokens/s | 有效上游输出 Token / 生成秒数；缺少输出用量或有效时长时 NULL，零输出为0。日志 trace 保存 generation_time_ms、timing_mode，支持核对。 |
| 请求、成功、失败 | 仅 operation=chat 的终态；failure 包含 failure 和 client_cancelled，失败率=失败/请求×100%。模型目录和预检不计入推理统计。 |
| 活跃用户 / 平均性能 | 对筛选范围内非空用户 ID 去重；性能均值使用有效请求样本加权，不平均各小时的均值。失败与取消若已获得指标仍保留。 |

无记录时 Token 总和0；有记录但所有样本均未上报某字段时该字段为不可用。部分已上报时仅求已知值的和，返回每个 Token 字段的 samples 及 usage_unavailable 请求数。不能把这些值解释为遗漏请求的完整消耗。

## 聚合与一致性

Migration0009建立 usage_hourly、usage_daily 并回填已有 Chat 日志；0010将Token累加字段扩展为Numeric(38,0)，避免累计值超过单条BIGINT容量。表以北京时间小时/日期及用户、组、Key、Provider、请求模型、最终逻辑模型、协议为复合主键，无关联对象级联删除。未知维度使用0或空串，事实日志仍保留NULL。

日志插入 RETURNING id 成功后才更新小时及日表，三者同一事务；重复Request ID、并发重试和磁盘outbox重放不会重复累加。任一汇总写入失败则日志与两张表一起回滚，受保护的待写文件继续重试。进程在终态前崩溃或数据库与磁盘同时不可写的已有限制仍适用。

统计按天查询使用完整日表和边界小时表，按小时查询使用完整小时表。精确[start,end)区间的两侧使用最多两段、各不超过一小时的索引日志查询；不用一次全范围日志扫描校准边界。总览与时间序列由同一SQL语句快照产生。UTC存储、Asia/Shanghai分桶，参数必须含时区；默认7天，最多366天。时间序列返回有请求的桶，空区间保留坐标系及无数据说明。

## API 与页面

| 接口 / 页面 | 权限与筛选 |
| --- | --- |
| GET /api/admin/usage；/admin/usage | admin / super_admin。user_id、user_group_id、api_key_id、provider_id、model、protocol、start、end、grain(hour/day)。模型匹配请求或最终逻辑模型，不重复计数。 |
| GET /api/portal/usage；/portal/usage | 所有已登录且完成首次改密用户。强制 actor.id，只允许 Key、模型、时间及粒度筛选；额外传 user_id/Provider 不能改变范围，其他用户Key只返回空结果。 |

页面展示指标卡片、Token/请求/失败率/TTFT/Tokens/s趋势图及明细时间表。点击管理端图表数据点带入对应[start,end)及维度跳转调用日志；日志查询补充协议过滤。总览日志链接仅在范围≤31天时展示，以兼容日志页限制。用户详情、账号详情和本人API Key列表分别预置相应统计筛选；普通用户无管理员统计或上游账号信息。

## 验收与部署

- Vue TypeScript / Vite / Docker构建、Python编译通过。
- stage13_acceptance.py：真实Nginx→FastAPI→HTTPX→临时HTTP/SSE协议服务，正常、错误、取消、重试、校验、隐私allowlist、日志补写、并发访问及重启保留通过。心跳和角色块之后延迟内容，TTFT和生成时长符合实际等待，缺失usage不伪造。
- 小时与日汇总、精确时间边界、所有维度、活跃用户去重、性能加权均值与直接call_logs逐条计算一致；6个并发同Request ID仅写一次，汇总异常事务回滚。普通用户403管理查询，本人用量无法越权，未登录401。
- stage13_migration.py：隔离临时数据库0008历史日志升级、回填、排除预检、北京时间跨日、大数累计、降级/再升级通过。未删除业务数据库。
- stage13_startup.py：全新0700挂载目录、完整迁移、随机管理员与强制改密、密钥和outbox权限通过。
- stage13_resource_regression.py：真实排队SSE的TTFT包含超过100ms等待；四级占用、队列满/超时/取消/Key撤销、实际配额/不确定预算、崩溃清算、并发管理请求和配置恢复通过。
- stage13_streaming_regression.py：真实curl -N、UTF-8/CRLF分帧、tools/usage、上游响应头与流中异常、12次取消/响应头前取消、ASGI2.4资源回收通过；测试清理阶段缺少SQL导入曾失败，修正并按已捕获Request ID恢复该夹具后完整重跑通过。
- 浏览器核对真实临时调用数据：3请求、2成功、1失败、总Token12，趋势点跳转日志为3条；截图 stage13-usage.png。截图数据仅用于验收，结束后清理。

升级前备份 `/data/backup/stage13-before-upgrade.sql`。继续沿用原 /data 和加密主密钥；原用户摘要保持一致。真实启用Provider仍为0，付费上游性能与各供应商usage差异待实际账号配置后验证。
