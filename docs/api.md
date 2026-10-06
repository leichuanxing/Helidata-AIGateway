# API文档 · 0.20.0

机器可读完整字段、校验和路径见`openapi.json`（由最终应用导出），在线为`/openapi.json`。文档不包含生产Key。管理API一般返回`{"data":...}`；分页包含items/total/page/page_size。推理API保持目标协议结构。每次请求有服务器生成的`X-Request-ID`，API响应设置no-store。

## 身份与权限

网页通过`POST /api/auth/login`取得Bearer Access Token及Refresh/CSRF Cookie。`POST /api/auth/refresh`必须携带对应Cookie和`X-CSRF-Token`，Refresh一次性轮换。`GET /api/auth/me`、`POST /api/auth/logout`、`POST /api/auth/change-password`提供会话管理。登录限流、来源校验和强制改密启用。用户禁用、Key撤销、密码变更即时影响后续鉴权。

调用接口使用个人门户生成的网关API Key：`Authorization: Bearer sk-hd-...`。不要使用Provider的Key。Anthropic Messages还支持`x-api-key`网关Key。普通用户只访问自己的门户/用量；管理员管理业务；超级管理员独占系统设置、备份和运行容量详情。

## 业务管理

| 路径族 | 方法与用途 | 权限 |
| --- | --- | --- |
| /api/admin/users | GET/POST；/{id} GET/PATCH/DELETE；/{id}/reset-password POST | 管理员，角色提升受限制 |
| /api/admin/user-groups | GET/POST；/{id} GET/PUT/DELETE | 管理员 |
| /api/admin/providers | GET/POST；/{id} GET/PATCH/DELETE；/{id}/test POST | 管理员 |
| /api/admin/providers/{id}/model-mappings | GET/POST；/{mapping_id} PUT/DELETE | 管理员 |
| /api/admin/providers/{id}/discover-models | POST，实际请求上游模型列表 | 管理员 |
| /api/admin/logical-models | GET | 管理员 |
| /api/admin/model-groups | GET/POST；/{id} GET/PUT/DELETE | 管理员 |
| /api/portal/api-keys | GET/POST；/{id} GET/PATCH/DELETE | 本人 |
| /api/portal/models、/api/portal/quota、/api/portal/usage | GET，本人授权目录/配额/统计 | 本人 |
| /api/admin/call-logs | GET过滤分页；/{request_id} GET详情 | 管理员 |
| /api/admin/usage、/api/admin/dashboard、/api/admin/resource-status | GET | 管理员 |
| /api/admin/audit-logs | GET；/{id} GET，不提供修改/删除API | 管理员 |
| /api/admin/runtime | GET，共享池和容量，不返回代理地址/密钥 | 超级管理员 |
| /api/admin/backups | GET/POST(202)；/{UUID}/download GET | 超级管理员 |

智能路由`/api/admin/smart-route`下提供configs、samples、logs、statistics及samples/{id}/vectorize。内容审核`/api/admin/compliance`下提供words、samples、policies、logs及samples/{id}/vectorize。精确前缀和请求模型以OpenAPI为准；删除在用对象受保护，历史调用与审计快照保留。

## 设置

`GET /api/public/settings`匿名可读基础品牌、URL、语言、显示时区，白名单不包含网关/安全/日志配置。`GET /api/admin/settings`及`PATCH /api/admin/settings`只允许超级管理员。PATCH带当前revision和任意待更新section：

```json
{"revision":0,"basic":{"system_name":"合力数据AI网关","timezone":"Asia/Shanghai"},"gateway":{"nonstream_timeout":120}}
```

成功revision加1并立即发布到本进程；过期revision返回409 `SETTINGS_CHANGED`。省略字段保持原值。四个section为basic/gateway/security/logging；未知字段422。Logo/Icon只接受≤256KiB且尺寸≤2048的PNG Data URI。URL只允许http/https且不能包含凭据、查询和片段。显示时区不改变配额/统计业务时区。敏感基础设施配置不能通过API读取或改写。

正文预览默认关闭；开启后详情增加request_body/response_body，列表不返回正文。每份≤16KiB，正则脱敏超时失败闭合。历史已保存预览不会因关闭开关自动擦除，按保留策略清理。 retention_days范围366–3650。

## 推理协议

| 路径 | 请求核心字段 | 说明 |
| --- | --- | --- |
| GET /v1/models | 无 | 只返回本Key授权逻辑模型 |
| POST /v1/chat/completions | model、messages、可选stream | OpenAI Chat；SSE以data事件和[DONE]终止 |
| POST /v1/responses | model、input、可选stream | 原生Responses；需Provider支持 |
| POST /v1/messages | model、messages、max_tokens、可选stream | 原生Anthropic或Chat/Messages适配 |
| POST /v1/embeddings | model、input | 实际Embedding数据，维度来自上游 |
| POST /v1/rerank | model、query、documents | 实际相关性排序；需Provider支持 |
| POST /v1/images/generations | model、prompt | 原生图片生成；需Provider支持 |
| POST /api/gateway/preflight | model | 验证授权/调度前置状态，不执行生成 |

模型映射改写上游model，对外返回逻辑model。请求依次经过鉴权、用户/组权限、内容审核、智能路由、模型选择、Provider调度、配额、四级容量、协议适配、上游、用量与日志。失败切换遵守错误类型和配置，不将参数错误或本地HTTP池容量错误当供应商故障。

```json
{"model":"your-logical-model","input":["需要向量化的文本"]}
```

上述为Embeddings请求核心字段；Chat与SSE的curl见README。接口存在不等于当前供应商已支持或已完成付费端到端验收。Chat/Messages转换边界及不支持参数会返回明确错误，不凭空执行工具。

## 错误、日志和限制

错误体含error.code/message/type/request_id，Anthropic路径采用其错误外层结构。401身份、403授权、413体积、422校验、429配额/排队、502上游故障、503依赖/HTTP池容量、504超时。准备队列也可返回429 `PREPARATION_TIMEOUT`或`PREPARATION_QUEUE_FULL`。

调用日志每Request ID一个持久终态；SSE开始后的失败HTTP状态保持200，以终态和错误事件判定。未知usage不估算消费。调用过滤默认7天、区间≤31天、每页≤100；统计查询最长366天。正文、Key、代理密码与原始上游错误不写常规运行日志。受控正文预览是显式开启的独立数据库字段。

账号新增/编辑支持 `protocol_config`：以 `openai-completions`、`openai-responses`、`anthropic-messages`（可同时选择）或独立 `ollama` 为键，值为 `{ "path_prefix": "/v1", "auth_type": "bearer" }`。Anthropic 也允许 `x-api-key`。路径前缀可留空，不允许查询参数、片段或路径穿越。`protocol` 保留为主协议及旧接口兼容字段。`default_test_model` 为本账号已启用映射的逻辑模型名，传 null 清空。连接测试只读取模型列表，可返回 `test_model`、`model_available`，未找到返回 `TEST_MODEL_NOT_FOUND`，不改变账号的正常连接状态。

智能路由保留 `/api/admin/smart-route` 接口兼容性：样本列表支持classification/q筛选；日志支持q（Request ID/模型/规范化文本）、source（local_rule/vector/fallback/error/legacy）、request_kind（real/preview），新增GET `/logs/{id}` 详情。预览保存独立决策，返回request_id/source/confidence/normalized_text/evidence；本地精确匹配时embedding_request_id为空。CSV保留两列模板兼容，允许similarity_threshold与remark可选列。统计含previews计数和source分布，Token不重复计Embedding子调用。

模型供应商新增protocol_type（text/image/vector，历史账号可空）、account_type；GET列表支持protocol_type/具体protocol及账号或模型q搜索，返回models与effective_protocol_type。POST创建须提交1至100条model_mappings。POST /api/admin/providers/{id}/test-models须提交consent=true、models和expected_config_version；包含图片需image_consent=true；结果含request_id、operation、success、error_code及已上报total_tokens。原/test保留只读模型列表连接检查，不发起生成。删除账号同步软删除映射并保留历史，唯一被路由引用的向量模型禁止移除。
