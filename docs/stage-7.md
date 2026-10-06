# 阶段 7：Gateway Core 基础链路

2026-10-04，应用 0.7.0，镜像 helidata-ai-gateway:stage7，数据库仍为 Migration0006。本阶段不需要新增业务表。访问 http://192.168.31.97:18080 。

## Pipeline 与模块边界

backend/app/gateway/pipeline.py 只组织流程。独立模块包括 request_id、authentication、user_validation、group_validation、model_permission、quota、concurrency、compliance、smart_routing、model_selection、provider_scheduler、provider_concurrency、protocol_adapter、upstream、usage、call_log。GatewayContext 每次请求独立创建，不共享用户、候选、密钥或状态。

认证模块逐请求查询 API Key、用户和用户组的同一数据库快照，随后独立验证用户状态、首次改密及组状态。既有身份和模型目录接口复用拆分后的认证校验，不建立过期权限缓存。模型权限按当前组授权查询；候选过滤禁用/删除账号与映射、不健康及冷却账号，按优先级选择首个候选并绑定真实协议 Adapter。预检不发出 HTTP 请求，成功表示授权、候选及 Adapter 配置通过，不代表真实上游连通或生成已验证。

配额、两级并发扩展入口、合规和智能路由目前明确标为 deferred，响应包含后续阶段编号；生成调用保持关闭。实际四级并发/排队/原子额度执行为阶段11，健康调度/故障转移为阶段10，智能路由为阶段16，合规为阶段17。没有把空 Hook 解释为已执行策略。usage 当前只记录真实 elapsed_ms，不编造 Token、TTFT 或 Tokens/s；本阶段 call_log 是脱敏结构化运行日志，调用日志业务表和界面在阶段12完成。

## 接口

GET /v1/models 使用网关 API Key，返回 object:list/data，模型 id 为授权逻辑名称，跨组去重。不返回真实上游模型名、账号信息或密钥。禁用模型组移出列表；没有可用映射的已授权逻辑名仍可列出，预检时返回503。

POST /api/gateway/preflight，Bearer API Key，JSON 为 {"model":"逻辑名称"}。执行认证至 Adapter 绑定完整基础链路；返回 model、ready、inference_enabled:false 和 deferred。没有上游请求或 Token 消耗。禁止未授权模型，映射不可用返回 NO_AVAILABLE_PROVIDER。该接口只做配置预检，不作为推理入口；生成能力按下一阶段接入。

## Request ID、错误与日志

所有经过 FastAPI 的请求由服务器生成 req_ 加32位随机十六进制 ID，不信任客户端自报 ID，响应 X-Request-ID 与错误体一致。ContextVar 在请求完成/异常时重置，并发请求不串号。API/v1 响应 no-store。

业务错误、参数校验、HTTP404/405及意外500统一为 error:{message,type:"gateway_error",code,request_id}。意外500只报告服务不可用及错误类型日志，不回显异常正文。校验错误不返回输入值。

Pipeline成功/失败结构化日志与HTTP完成日志携带同一ID；日志字段只允许操作、结果、错误代码、阶段和耗时，不记录请求正文、Authorization、密钥、上游URL或真实模型名。Nginx访问日志使用上游响应ID，去掉查询串和原始请求行；Uvicorn重复访问日志关闭，启动/非请求日志不带请求上下文时标记为“-”。业务调用日志持久化与检索仍按阶段12实现。

## 验收与部署

tests/stage7_acceptance.py 使用临时真实数据库记录，通过运行中的Nginx/FastAPI验证目录、预检、API Key最后使用、权限/禁用/首次改密/冷却、并发请求ID唯一，以及401/403/404/405/422/503错误格式。在ASGI测试实例注入意外异常，验证500脱敏和响应ID；捕获真实日志验证成功/失败Pipeline与HTTP日志的ID贯穿及敏感数据不泄露。预检配置故意指向本机关闭端口，仍成功证明没有上游网络请求。临时记录随后清理。第6阶段映射、目录授权、分页和竞态验收全部回归。

Python编译、Vue/TypeScript/Vite、Docker构建通过，阶段7镜像健康。隔离0700新数据卷启动验收覆盖初始化、Migration0006、首次改密与目录权限。浏览器检查新版登录页正常打开；运行状态页与/v1/models导航被浏览器客户端拦截，未完成这两项浏览器检查。服务健康与未认证错误格式已由服务器端HTTP验收覆盖。截图为stage7-login.jpg。

升级前备份 /data/backup/stage7-before-upgrade.sql；原用户/密码状态摘要一致，管理员密码和Master Key保留。隔离测试容器和临时记录清理。按计划本阶段结束后停止，下一阶段为阶段8 OpenAI Chat Completions；没有真实上游Key，不声称完成付费上游生成。
