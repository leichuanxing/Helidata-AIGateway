# 阶段15：扩展API协议能力

状态：实现已部署，自动验收通过；真实供应商验收待配置。应用0.15.0，Migration0011，镜像helidata-ai-gateway:stage15。阶段16尚未开始。

## 接口与适配范围

| 网关接口 | 模型类型 | 上游范围 | 流式 |
| --- | --- | --- | --- |
| POST /v1/responses | text/reasoning/multimodal | OpenAI协议且支持Responses的服务 | 原生SSE |
| POST /v1/messages | text/reasoning/multimodal | Anthropic原生；OpenAI Chat转换 | 原生/转换SSE |
| POST /v1/chat/completions | text/reasoning/multimodal | 原OpenAI；Anthropic Messages转换 | 原生/转换SSE |
| POST /v1/embeddings | embedding | OpenAI兼容Embeddings | JSON |
| POST /v1/rerank | rerank | custom_openai配置的兼容Rerank服务 | JSON |
| POST /v1/images/generations | image | OpenAI兼容Images | JSON |

其他接口使用Authorization: Bearer网关Key；Messages还支持x-api-key。两个凭证同时存在且不一致返回401。原生请求允许供应商扩展字段，经2MiB限制和必要字段校验后转发；映射的上游模型名替换逻辑模型，返回顶层/流式message或response的model恢复为逻辑模型。原生供应商若不支持某接口，将返回明确上游错误，不把协议类型等同于每个接口都可用。Ollama原生协议未扩展，配置OpenAI兼容端点时按OpenAI能力使用。

Responses仅实现同步创建与SSE创建；background=true不支持。未实现Response查询/删除/取消/WebSocket、批量请求、图片编辑或图片流。previous_response_id原生转发，关联状态属于供应商和账号；多账号切换无法保证跨账号历史状态可用，客户端宜传完整输入或为该模型配置单一账号。

## 统一链路

全部推理操作进入原认证、用户/组状态、模型权限、模型类型、准入、账号调度、四级并发/队列、Token预算和实际结算、健康/故障转移、终态日志链路。有限Token配额下，Responses预留/注入max_output_tokens，Messages使用max_tokens，Chat保持原max_completion_tokens；Embedding/Rerank只预留输入预算，不注入文本生成参数。图片Token预算为保守输入加输出预算，不能代表图片货币价格。无usage保持未知/未上报预算，不根据请求估算实际Token。

非流响应限制8MiB，图片响应32MiB，单个SSE事件1MiB。请求与调度保留120秒期限，流式读取采用配置的空闲超时。收到错误/不完整EOF不伪装成功；客户端断开取消上游并释放租约。共享流式响应类维护ASGI断开监控、幂等关闭、配额结算和唯一日志。

## 原生协议与转换

各原生响应校验、流式状态和usage分别位于providers/protocols/responses.py、messages.py、embeddings.py、rerank.py、images.py，路由只调用GatewayPipeline。共享HTTP层负责网络、鉴权头、超时、体积限制及脱敏异常。Messages错误采用type:error包络，流式error使用对应事件格式。

Chat与Messages双向转换独立在translator.py。支持文本、system/developer转system、URL/base64图片、函数工具定义、工具选择、tool_use/tool_calls及tool_result/tool消息。转换SSE逐事件输出文本和JSON片段，保留工具编号关联、停止原因与usage，不缓冲完整答案；流式工具JSON有界验证。system必须在普通消息前，n必须为1。

无法保留语义的结构化输出、思考/签名块、原生服务器工具、音频、函数旧协议、未知扩展、缓存控制、引用元数据和仅预热缓存请求等明确PROTOCOL_ERROR。请求转换在配额预留和网络调用前检查。响应无法转换时明确失败；响应头已发送时通过SSE error报告，终态日志记录失败。该实现不是对所有供应商扩展的无损转换承诺。

## 用量与页面

Migration0011为小时/日汇总增加operation维度并扩展主键，Chat历史标记chat；升级从日志回填五种新操作，降级仅保留旧版本理解的Chat汇总，再升级从日志重建。原0009迁移冻结维度和投影，避免全新启动受当前服务变化影响。统计查询显式列顺序，防止ALTER增加列后UNION错位。

用量统计与Dashboard默认包含全部6种推理操作；管理/本人用量可按operation筛选，日志筛选同步扩展，图表与失败卡片不再强制chat筛选。Token仅取上游reported usage：Responses/Images input/output/total映射，Anthropic输入包括input_tokens、cache_creation_input_tokens、cache_read_input_tokens，输出为累计output_tokens。缓存计数单列保留，缺失值不补零。Rerank billed search_units不冒充Token，Embeddings没有输出Token时该字段未知。TTFT仅统计有效生成内容，图片/Embedding/Rerank不生成虚假Tokens/s。

模型广场显示API Base URL及各接口认证说明，运行状态动态显示服务阶段。API Key/正文/生成内容不进入日志或统计。

## 验收与限制

主验收tests/stage15_acceptance.py通过真实Nginx/FastAPI/HTTPX连接本机HTTP协议夹具，并核对数据库和Redis；夹具响应是测试数据，不能冒充真实模型生成。tests/stage15_translation.py验证图片、函数工具、编号、JSON片段和不支持语义；stage15_startup.py验证0700新卷；stage15_migration.py验证独立卷升级/降级/回填幂等。阶段13用量/四级资源/流式及阶段14Dashboard回归沿用真实HTTP夹具。最终结果见stage15-validation.txt。

计划要求每个接口至少一个真实Provider可调用。目前没有启用的真实Provider，尚未收到用户配置的服务，故这一条生产验收未完成。实现和测试可继续完成，不能声称阶段15已完全验收或真实供应商性能已验证。原用户密码状态与/data加密主密钥保留，备份/data/backup/stage15-before-upgrade.sql。

## 官方规范依据

- [OpenAI文本生成](https://developers.openai.com/api/docs/guides/text)、[Responses流式事件](https://developers.openai.com/api/docs/guides/streaming-responses)
- [OpenAI Embeddings](https://developers.openai.com/api/docs/guides/embeddings)、[Images](https://developers.openai.com/api/docs/guides/image-generation)
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[流式Messages](https://platform.claude.com/docs/en/build-with-claude/streaming)
- [Cohere Rerank字段规范](https://docs.cohere.com/reference/rerank)，用于兼容Rerank请求/结果校验；未增加独立Cohere账号类型。


## 最终自动验收结果（2026-10-05）

主验收7组EXIT0；文本/图片/函数工具及转换边界语义补测EXIT0；全新0700卷启动EXIT0，独立卷Migration0011降级/重升级3组通过。原用量9组、四级资源/队列/配额15组、SSE6组、Dashboard4组回归均EXIT0。最终主验收还核对非流/流式Responses失败时已上报Token保留。Python编译、Vue类型检查、Vite与最终Docker构建通过。

浏览器确认4个实际HTTP夹具调用计入Dashboard（3成功/1失败、16总Token）；Responses独立统计为3请求/2成功/1失败、12总Token，操作筛选、失败联动、模型广场接入说明及运行状态阶段15显示通过。截图包含已清理临时数据，截图中的模型不是已配置生产模型。

临时用户/模型/Provider映射/日志/小时日汇总/配额预留/outbox/全局执行/流式/队列及队列租约已清理，原用户状态摘要匹配；配置500/1000/30/300，本容器及既有其他应用健康。实际并发采样保留为运行历史。最终镜像身份和详细证据见stage15-validation.txt。每种接口的真实Provider调用验收未完成，阶段16未开始。
