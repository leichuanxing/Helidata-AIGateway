# 阶段 8：OpenAI Chat Completions

实现版本：应用0.8.0，镜像helidata-ai-gateway:stage8，数据库Migration0006（无新增表）。本阶段实施非流式Chat Completions，SSE按阶段9实现。

2026-10-04，已部署并通过本阶段可执行验收、Gateway Core和Provider回归、隔离新数据卷启动验证。真实付费上游账号仍待录入后验证。下方说明当前实际能力与范围。

## 接口与调用链

GET /v1/models 只返回当前用户组已授权、模型组启用且至少有一个可用映射的逻辑名称，跨组去重，按 [OpenAI Docs：List models](https://developers.openai.com/api/reference/python/resources/models/methods/list) 返回id/object/created/owned_by，created来自逻辑模型实际创建时间。可用映射排除禁用/删除、不健康和冷却账号。用户中心目录仍可显示授权但不可用的模型，标准API列表更严格。

POST /v1/chat/completions 经统一Pipeline完成API Key、用户、用户组、模型权限、逻辑映射、账号选择、Adapter、HTTPX和上游调用。只选择OpenAI兼容协议的账号；支持OpenAI、DeepSeek、Aliyun、vLLM、SGLang、自定义兼容服务，以及配置为OpenAI协议的Ollama。原生Anthropic/Ollama转换属于后续多协议阶段，不以不兼容的原生响应冒充OpenAI响应。Embedding/Rerank/Image逻辑类型不能调用Chat接口。

输入按 [OpenAI Docs：Create chat completion](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) 核对，支持model、messages、temperature、top_p、max_tokens、stream、tools、tool_choice、response_format。同时透传max_completion_tokens与未知供应商扩展JSON字段，不静默丢弃。messages支持developer/system/user/assistant/tool及旧function角色、字符串或内容数组、多模态内容和工具回合。网关不执行工具函数。上游是否支持某个选项由所选服务决定，拒绝时返回统一错误。

请求model只在服务器端替换为配置的真实上游模型；响应model恢复为客户端逻辑名称。其他有效Chat Completion字段，包括choices、tool_calls、finish_reason、usage及扩展字段保持上游结果。网关校验基本响应结构，不自行编造生成内容或Token用量。完整统计和计费仍为后续阶段。

stream默认false，显式true返回501 STREAM_NOT_IMPLEMENTED，不发起上游调用或静默改成非流式。预检接口继续不访问网络，inference_enabled现在按协议/模型类型报告当前非流式能力。

## 边界与错误

输入最多1000条消息、序列化后2MiB；temperature为0–2，top_p为0–1，输出Token上限必须为正整数。校验错误不回显输入。未知扩展保持原样，由上游做语义校验。

真实HTTPX请求保持TLS校验、显式代理、不使用环境代理、不跟随重定向；连接最多10秒、Chat总期限120秒、响应最多8MiB。模型发现仍使用原10秒/1MiB限制。等待上游前释放数据库事务/连接。服务器生成的Request ID传到上游并关联既有日志；不使用客户端自报ID，不传客户API Key到上游。

上游400/422返回400 UPSTREAM_REQUEST_REJECTED，401/403返回502 UPSTREAM_AUTH_FAILED，429返回503 UPSTREAM_RATE_LIMITED，超时504 UPSTREAM_TIMEOUT；网络、其他HTTP、非法JSON/响应结构和超限均为脱敏502。错误体不返回上游正文、密钥或错误详情。不重试、不自动切换账号，完整健康调度/Failover属于阶段10，避免现在重复发送计费请求。

## 使用

先在账号池配置真实上游地址/Key并创建逻辑映射，创建启用模型组，给用户组授权并分配用户；用户创建自己的网关API Key。下例变量由调用者配置，不将真实凭据写入源码或交付文档：

```bash
export GATEWAY_URL=http://192.168.31.97:18080
# 在当前终端设置 GATEWAY_API_KEY；值来自“我的 API Key”首次创建结果。
curl "$GATEWAY_URL/v1/models" \
  -H "Authorization: Bearer $GATEWAY_API_KEY"

curl "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"你好"}],"max_tokens":32,"stream":false}'
```

deepseek-chat为示例逻辑名称，需事先配置；没有可用映射时返回错误，不提供伪造回答。

## 验收范围

tests/stage8_acceptance.py通过实际Nginx/FastAPI/数据库/HTTPX和临时HTTP协议夹具验证整条链路，含真实curl、映射改写、响应逻辑名、字段与usage保留、工具/多模态消息、输入/授权/流式拦截、上游错误/重定向/响应大小、超时、实时启停/冷却、严格模型列表和并发Request ID。应用源码没有测试回答或模拟Provider；夹具仅在验收脚本中，验收结束后清理。

tests/stage8_core_regression.py沿用阶段7的认证、日志和意外500回归，按已开放的非流式能力更新预检预期；tests/stage8_startup.py验证严格0700新数据卷和初始化。Provider Adapter原有发现/协议/代理/加密回归仍使用阶段5测试。

执行结果见stage8-validation.txt。真实HTTPX与curl链路、字段与工具回合、错误与超限、缩短总期限后的504、严格模型列表与8并发请求ID均通过；Core与Provider回归、0700新数据卷启动也已通过。超时测试使用真实延迟HTTP夹具及测试进程中的期限覆盖，生产期限仍为120秒。

Docker复用已有系统依赖层，将curl单独安装，减少重复依赖下载；镜像构建与前端编译通过。升级前备份/data/backup/stage8-before-upgrade.sql；原用户/密码状态摘要一致，Master Key保持。临时验收账号/模型/Key/映射已清理，启动测试容器已移除。

当前没有启用的真实上游账号，不能声称付费账号鉴权或真实模型生成已验证。配额/四级并发仍为阶段11，调用日志业务表与统计为阶段12–13，合规/智能路由为阶段16–17；本阶段只接入已完成基础链路和非流式协议调用。按开发计划，本阶段交付后停止，下一阶段为阶段9 SSE Streaming与客户端断开。
