# 阶段17：内容合规

2026-10-05，Asia/Shanghai。依据分阶段计划、完整开发提示词和Excel D-05至D-08。阶段18未开始。

## 页面与数据

管理员页面：`/admin/compliance/words`、`/samples`、`/policies`、`/logs`；接口在 `/api/admin/compliance`。敏感词、审核样本、策略支持新增、编辑、删除；样本支持重新向量化和状态筛选；策略引用词/样本，可限定用户组和模型，未指定范围时适用全部。普通用户接口403、页面重定向。Block表单明确显示业务影响。

Migration0014新增 `sensitive_words`、`review_samples`、`review_vectors`、`compliance_policies`、`compliance_logs`。API的kind代表匹配方式，risk代表风险级别。规则上限500、样本上限500、策略上限100，每策略最多100个词及100个样本引用。样本按trim后的文本SHA256去重；删除被引用的词/样本返回409；删除样本级联删除向量，历史审核证据保持。

词支持普通文本、通配符、正则。普通文本Unicode NFKC规范化并忽略大小写；通配符*、?按片段匹配。正则保存前校验，每条最多20ms，整次词匹配预算100ms，超时503并且不调用上游。

## 本地语义审核与任务

使用固定版本多语言E5-small ONNX int8 CPU模型，输出384维单位向量；没有运行时下载或Provider Embedding调用。模型Hub仓库 `Xenova/multilingual-e5-small`，修订 `761b726dd34fb83930e26aab4e9ac3899aa1fa78`。模型文件SHA256 `f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193`；tokenizer摘要 `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39`。构建时再次核对摘要。来源：[模型版本](https://huggingface.co/Xenova/multilingual-e5-small/tree/761b726dd34fb83930e26aab4e9ac3899aa1fa78)、[原始模型说明](https://huggingface.co/intfloat/multilingual-e5-small)。

二进制文件不加入Git。首次重建先运行 `python docker/fetch_compliance_model.py`，下载固定版本并验证后原子安装，再构建Docker。模型随镜像发布；业务请求不发送给模型下载站。

样本最大2000字符，pending/processing/ready/failed；后台本地向量化，超过60秒未完成的processing任务递增修订后恢复。写入短事务核对样本ID、修订和processing状态，防止过期任务覆盖编辑/重试结果。数据库验证384维非零向量；启用语义策略前必须全部样本ready且当前模型版本一致。编辑或重试已启用策略引用的样本时，相关请求暂时503直到重新就绪。

每次文本最多16000字符/64KB，以256字符、224步长的重叠片段嵌入；模型tokenizer上限512 tokens。样本使用片段平均归一化向量，请求按各片段与样本最高余弦相似度判断。pgvector精确检索检查全部被引用的当前ready样本，最多500个，不让其他策略的高排名Audit候选遮蔽Block样本。没有近似索引。默认阈值0.85，需用实际业务样本校准，不能视为完备的风险识别保证。

CPU推理单线程执行器，最多一个执行及一个等待任务，ONNX内部CPU线程2；等待/执行15秒超时、容量不足或模型不可用返回503，避免绕过检查。取消后的已提交本地推理可能继续到完成，容量直到其结束才释放，不占Provider名额或付费Token。

## 请求链路与日志

认证、用户组和模型权限后，智能路由/模型选择/配额/四级并发之前审核。匹配的Block优先于Audit。Block返回403 CONTENT_BLOCKED，不执行AI-Auto计费Embedding子调用、不调用Provider、不占Provider并发；调用日志保留“未发送上游请求”，Token字段保持未上报，不能将未知用量伪造成供应商上报的0。

Audit命中保存审核证据后继续既有生成链路；实际生成用量沿用既有统计。审核日志写入失败不能阻断Audit：独立2秒数据库写入期限，失败写入 `/data/logs/compliance-outbox`（目录700，文件600），后台幂等补写；若磁盘也不可写，调用日志标记不可用。Block即使审核日志不可写仍拒绝请求。

标准Chat/Responses/Messages文本、Messages system与工具输入、文本Embedding、Rerank查询/文档和图片生成prompt进入检查。适用策略下非文本附件或Responses previous_response_id隐藏历史明确400拒绝，需要发送完整文本；不进行图像识别或生成后审核。preflight不做内容审核，不代表内容通过。已经审核的AI-Auto父请求通过服务端状态标记避免Embedding子请求重复审核，不接受客户端跳过标记。

审核日志仅保存Request ID、身份ID、模型、动作、策略名称/ID、词/样本ID、来源/风险、相似度、命中数量和耗时，不保存客户正文、命中片段或生成内容。每策略最多展示20条证据，完整命中数量保留。支持精确Request ID及最长31天时间范围、动作筛选和分页，连接调用日志及反向证据链接。

## 验收与部署记录

最终结果见 `stage17-validation.txt`。真实HTTP夹具与实际Nginx/FastAPI/PostgreSQL/Redis检查Block零上游记录、Audit继续和实际6Token、数据库锁超时落盘及恢复补写、本地真实ONNX+pgvector语义阻断、虚拟模型提前阻断、中断恢复、引用删除保护/向量级联/历史和租约释放。额外102个合成排序向量专门验证多策略候选完整性，不冒充真实样本生成质量验收。

浏览器检查敏感词保存、样本重新向量化、Block配置及影响提示、命中证据、Request ID联动、无Provider调用的链路详情、普通用户重定向及退出。截图 `stage17-evidence.png`、`stage17-block-call.png` 来自随后清理的隔离环境。

阶段16规则/样本/向量/决策快照、六种操作日志用量、原用户状态及Master Key在独立卷升级、0014降级0013、重升级和重复启动中保持；另验全新0700卷和两个受保护outbox目录。迁移回滚0013会删除阶段17五表及数据，需要保留时先备份并恢复完整数据库。

部署使用镜像 `helidata-ai-gateway:stage17`，应用0.17.0、health phase17、Migration0014。升级备份 `/data/backup/stage17-before-upgrade.sql` 权限600，沿用/data及Master Key，不预置业务词、样本或启用策略。阶段15/16真实付费Provider验收仍待账号配置；合规推理使用本地模型，HTTP生成夹具不代表真实供应商生成验收。
