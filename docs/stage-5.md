# 阶段 5：账号池与 Provider 管理

实现账号池分页查询（名称/供应商/协议/状态/健康状态）、新增、局部编辑、详情、启停、软删除及实际HTTP连接测试。管理员与超级管理员可管理；普通用户全部接口返回403。优先级和并发上限保存为后续调度策略，本阶段没有虚构实时负载。

Migration0005建立providers，含计划要求字段，以及config_version、最近测试、HTTP状态、延迟、错误代码和deleted_at。删除后停止新测试，保留历史关联。修改配置重置连接健康状态；测试过程中配置改变时，旧结果返回409且不覆盖新配置。

## 密钥

上游API Key使用AES-256-GCM加密，独立32字节随机Master Key位于/data/config/provider-encryption.key，root:gateway 640。12字节随机nonce、认证tag、固定版本AAD组成v1密文；同明文每次加密不同。数据库没有明文Key；HTTP响应只含has_api_key，不返回明文、密文或Key片段。

编辑留空保留原Key；明确clear_api_key才清除，可替换。云供应商要求Key，本地/自定义服务允许无Key。请求字段SecretStr防止对象表示泄露；错误和审计不记录密钥；连接测试不返回上游响应正文。

Master Key随/data持久化，不能用JWT密钥替代。启动检查全部已有密文能否解密；已有密文时缺失文件会阻止启动，不生成替代Key。备份数据库必须同时安全备份这个文件；单独SQL备份无法恢复上游凭据。当前没有在线Master Key轮换功能。

## 协议与类型

统一BaseProvider接口包含list_models/chat_completion/responses/messages/embeddings/rerank/image_generation。业务路由只使用统一registry，不散落供应商判断。OpenAI兼容、Anthropic原生和Ollama原生分别适配；类型包含OpenAI、DeepSeek、Anthropic、Aliyun、vLLM、SGLang、Ollama、Custom OpenAI。

OpenAI兼容支持非流式chat/completions、responses、embeddings、images/generations基础请求；Custom OpenAI附带rerank扩展。Anthropic使用x-api-key与anthropic-version，提供模型列表/messages；Ollama使用/api/tags、/api/chat、/api/embed。不支持的操作明确报UNSUPPORTED_OPERATION；流式不在本阶段开放。服务端是否支持某能力须以后续真实模型请求验证，类型名称不代表全部能力都可用。

Base URL包含API版本路径：OpenAI为https://api.openai.com/v1，DeepSeek为https://api.deepseek.com，Aliyun默认北京https://dashscope.aliyuncs.com/compatible-mode/v1（其他区域请修改），Anthropic为https://api.anthropic.com/v1；Ollama原生填写服务根地址。支持明确HTTP/HTTPS代理，不接受URL用户名密码、查询参数或fragment；带认证代理暂未支持。内网本地模型地址可用。

## 连接测试

读取模型列表：OpenAI/Anthropic为BaseURL+/models，Ollama原生为BaseURL+/api/tags。真实网络请求，不收费生成。报告network_connected、authentication、HTTP状态、毫秒耗时、返回模型数、错误代码；成功仅表示列表请求成功。

禁用账号拒绝测试且不发起上游请求。10秒超时、1MiB响应限制、固定TLS验证、禁用重定向和环境代理继承；避免Key随跳转发送到其他地址。401/403、HTTP错误、网络失败、格式错误和过大响应分别报告脱敏代码。成功更新healthy并清零failure_count；失败更新unhealthy和计数。自动健康巡检、冷却及调度在阶段7及后续阶段实现。

## API

| 路径 | 方法与用途 |
| --- | --- |
| /api/admin/providers/types | GET 类型/协议及默认地址 |
| /api/admin/providers | GET 分页筛选；POST 新建 |
| /api/admin/providers/{id} | GET 详情；PATCH 局部更新；DELETE 软删除 |
| /api/admin/providers/{id}/test | POST 实际连接测试 |

页面：/admin/providers、/admin/providers/:id，新增/编辑使用列表对话框。账号详情的模型发现和模型映射按阶段6继续。

## 验收与来源

tests/stage5_acceptance.py使用临时真实HTTP监听器验证三种协议、鉴权、代理、失败、禁用、并发配置修改、密文/审计和角色边界；监听器为自动化协议夹具，测试记录清理，不作为生产模型。tests/test_provider_crypto.py验证nonce随机性、篡改、错误key和缺失文件。tests/stage5_migrations.py临时库迁移；tests/stage5_startup.py隔离容器初始化。

没有用户提供的真实上游密钥，因此不能声称付费账号鉴权成功或真实模型生成验收通过；后续可在账号池录入实际账号并测试。已开发的连接测试会如实报告结果。

协议依据：[OpenAI模型列表](https://developers.openai.com/api/reference/overview)、[Anthropic模型列表](https://platform.claude.com/docs/en/api/http/models/list)、[Ollama模型列表](https://docs.ollama.com/api/tags)、[DeepSeek模型列表](https://api-docs.deepseek.com/zh-cn/api/list-models/)、[Aliyun Base URL](https://help.aliyun.com/en/model-studio/base-url)、[Cryptography AESGCM](https://cryptography.io/en/latest/hazmat/primitives/aead/)。

部署镜像helidata-ai-gateway:stage5，服务健康。升级前SQL备份/data/backup/stage5-before-upgrade.sql；Master Key保护副本/data/backup/provider-encryption.key（600）。验收记录stage5-validation.txt、截图stage5-provider-detail.jpg；截图临时账号随后清理。账号编辑的updated_at异步读取已修复，全部后台验收与阶段4回归通过。下一阶段为模型映射与模型组，本阶段停止。
