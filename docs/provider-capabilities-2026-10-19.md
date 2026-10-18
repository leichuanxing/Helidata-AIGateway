# 供应商重排序与文生图能力核对

日期：2026-10-19。下表描述**当前网关预设和协议适配范围**，不代表供应商所有产品能力，也不代表每个模型都具备对应能力。

## 能力矩阵

| 供应商 | 重排序 | 文生图 | 说明 |
| --- | --- | --- | --- |
| OpenAI | 未接入 | 支持 | 使用 Images API 专用模型 |
| DeepSeek | 未接入 | 未接入 | 当前预设以对话协议为主 |
| 智谱开放平台 | 未接入 | 支持 | 使用图像模型及对应地域 Key |
| 智谱 Coding Plan | 未接入 | 未接入 | 套餐对话接入，不能套用开放平台能力 |
| Anthropic | 未接入 | 未接入 | 当前 Messages 接入 |
| 阿里云百炼 | 支持 | 支持 | 按量付费账号；排序转换为原生 DashScope；生图限兼容 Images API 的模型 |
| vLLM | 条件支持 | 当前文本预设未接入 | 重排需部署 pooling/score 模型，普通 Chat 模型不能重排 |
| SGLang | 条件支持 | 条件支持 | 分别指向重排实例或 SGLang Diffusion 图像服务 |
| Ollama | 当前预设未接入 | 当前预设未适配原生生图 | 不把原生接口能力当作 OpenAI 兼容接口能力 |
| Custom OpenAI | 条件支持 | 条件支持 | 上游必须实际提供 rerank / images/generations |
| 腾讯云 TokenHub | 未接入 | 原生接口尚未适配 | Hy/WAND 等具有不同端点和响应，不直接当作 Images API |
| 百度千帆 | 当前预设未接入 | 原生/模型专属接口尚未适配 | 不能只打开开关后误发到通用端点 |
| 硅基流动 | 支持 | 支持 | 生图响应转换为统一 data 格式；单次一张，URL 输出 |
| 火山方舟 | 未接入 | 支持 | 使用 Seedream 等图像模型的 Images API |
| MiniMax | 未接入 | 原生接口尚未适配 | 当前预设不把其他格式冒充 OpenAI Images API |
| 小米 | 当前预设未接入 | 当前预设未接入 | 当前对话接入 |
| Kimi | 当前预设未接入 | 当前预设未接入 | 当前对话接入 |
| OpenCode | 当前预设未接入 | 当前预设未接入 | 当前模型对话端点表 |
| OpenRouter | 当前预设未接入 | Chat 图像输出尚未适配到 Images API | 不能据此判断其平台不支持生成图片 |
| Gemini | 未接入 | 支持 | 使用支持 OpenAI 兼容 Images API 的图像模型 |

Coding/Token Plan 等独立套餐继续使用自己的协议清单，不继承同供应商按量付费账号的新能力。当前未适配的供应商会显示“当前接入或套餐未适配”及具体说明，避免将网关适配限制误标为模型不支持。

## 修复内容

- 补齐能力表、套餐边界、前端类型选择、后端兼容判断和适配器选择，移除“重排只能 Custom OpenAI”的硬编码。
- 接通推理执行入口的 vendor rerank/image 方法；直接调用和负载均衡统一调用均使用同一适配链路。
- 阿里云排序转换为 `input` / `parameters` 请求和统一 results 响应；默认排序基础地址 `/api/v1`，可更换为业务空间域名。转换兼容模式地址时仅改变路径，保留配置主机，不将私有代理密钥发送给官方域名。
- 硅基流动转换 size→image_size、images→data；移除默认 n=1，拒绝多图、b64_json 和已下线 batch_size 参数，拒绝发生在上游调用前。不自动重发多次收费请求、不下载远程图片。
- 修复图像调用沿用短默认超时的问题，使用系统非流式超时和有界响应大小。
- 供应商能力说明明确要求选择对应专用模型；不批量改写已有账号和模型配置。

## 官方依据

- [阿里云排序 HTTP 格式](https://help.aliyun.com/zh/model-studio/text-rerank-api)、[默认域名路径示例](https://help.aliyun.com/zh/es/user-guide/configuration-template-big-model-service-platform-refined)、[千问 Images API](https://help.aliyun.com/en/model-studio/qwen-image-generation-and-editing-api-reference)。
- [硅基流动重排](https://docs.siliconflow.cn/docs/api/rerank-post)、[生图 OpenAPI](https://github.com/siliconflow-inc/siliconflow-api/blob/main/openapi.yaml)、[生图接口变更公告](https://docs.siliconflow.cn/docs/release-notes/overview)。旧 OpenAPI 的 batch_size 字段已被新公告下线，以公告为准。
- [vLLM 重排](https://docs.vllm.ai/en/stable/models/pooling_models/scoring/)、[SGLang 重排路由](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/entrypoints/http_server.py)、[SGLang 图像路由](https://github.com/sgl-project/sglang/blob/main/python/sglang/multimodal_gen/runtime/entrypoints/openai/image_api.py)。
- [Gemini OpenAI 兼容生图](https://ai.google.dev/gemini-api/docs/openai?hl=zh-CN)、[火山图像生成 API](https://api.volcengine.com/api-docs/view?action=ImageGenerations&serviceCode=ark&version=2024-01-01)、[TokenHub 原生图像接口概览](https://cloud.tencent.com/document/product/1823/135744)。

## 验证边界

全量检查所有预设/套餐的声明与适配器一致性。HTTP 测试遍历当前开放的 13 个供应商/操作组合，覆盖物理模型和负载均衡别名、请求转换、响应校验及参数拒绝。实际经过隔离 FastAPI、HTTPX、Redis 和 PostgreSQL，上游使用本地可控服务。

未持有各商业供应商的全部 Key/模型权限，未做全部供应商付费实测；可选协议不等于每个部署实例或模型都支持。上线仍保留现有数据库、配置及主密钥，先备份再替换容器，失败回滚，不推送 GitHub。

## 最终验证
后端 116 项测试通过，前端 27 项测试通过，TypeScript 检查和生产构建通过。13 个已开放的供应商/操作组合均通过本地上游服务的真实 HTTP 直连及负载均衡调用测试；不等同于商业供应商真实付费调用验收。
