# 模型供应商及新增账号检查

日期：2026-10-12。版本仍为 v1.0.7，不推送 GitHub。默认值只影响新增账号及用户主动切换供应商/套餐，已有保存的账号地址与密钥不自动修改。

## 默认地址与图片

20 个供应商均有地址和本地 SVG 图片，39 种账号/套餐配置均有非空地址。不同协议的完整 API 基础地址在“服务 URL”区填写，协议配置不展示路径前缀。网关追加请求端点，不应把 /chat/completions 等端点再次填入基础地址。

| 供应商 | 标准账号默认基础地址 | 官方说明 |
|---|---|---|
| OpenAI | https://api.openai.com/v1 | [API](https://platform.openai.com/docs/api-reference) |
| DeepSeek | https://api.deepseek.com/v1 | [API](https://api-docs.deepseek.com/) |
| 智谱开放平台 | https://open.bigmodel.cn/api/paas/v4 | [API](https://docs.bigmodel.cn/cn/api/introduction) |
| 智谱 Coding Plan | https://open.bigmodel.cn/api/coding/paas/v4 | [各协议地址](https://docs.bigmodel.cn/cn/coding-plan/tool/others) |
| Anthropic | https://api.anthropic.com/v1 | [API](https://platform.claude.com/docs/en/api/overview) |
| 阿里云百炼 | https://dashscope.aliyuncs.com/compatible-mode/v1 | [地域与套餐地址](https://help.aliyun.com/zh/model-studio/base-url) |
| vLLM | http://127.0.0.1:8000/v1 | [自部署说明](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/) |
| SGLang | http://127.0.0.1:30000/v1 | [自部署说明](https://docs.sglang.io/docs/basic_usage/send_request) |
| Ollama | http://127.0.0.1:11434/v1 | [兼容接口](https://docs.ollama.com/api/openai-compatibility) |
| Custom OpenAI | http://127.0.0.1:8000/v1 | 用户自行指定实际服务，无统一公网地址 |
| 腾讯云 TokenHub | https://tokenhub.tencentmaas.com/v1 | [API](https://cloud.tencent.com/document/product/1823/130078) |
| 百度千帆 | https://qianfan.baidubce.com/v2 | [套餐文档](https://cloud.baidu.com/doc/qianfan/s/imlg0beiu) |
| 硅基流动 | https://api.siliconflow.cn/v1 | [API](https://docs.siliconflow.cn/docs/api/chat-completions-post) |
| 火山引擎方舟 | https://ark.cn-beijing.volces.com/api/v3 | [API](https://www.volcengine.com/docs/82379/1399008) |
| MiniMax（中国） | https://api.minimax.cn/v1 | [API](https://platform.minimax.cn/docs/api-reference/text-openai-api) |
| 小米 MiMo | https://api.xiaomimimo.com/v1 | [按量与套餐地址](https://mimo.mi.com/docs/zh-CN/tokenplan/integration/qwencode) |
| Kimi | https://api.moonshot.cn/v1 | [API](https://platform.kimi.com/docs/get-api-key) |
| OpenCode | https://opencode.ai/zen/v1 | [Zen](https://opencode.ai/docs/zen/) |
| OpenRouter | https://openrouter.ai/api/v1 | [API](https://openrouter.ai/docs/quickstart) |
| Gemini | https://generativelanguage.googleapis.com/v1beta/openai | [兼容接口](https://ai.google.dev/gemini-api/docs/openai) |

vLLM、SGLang、Ollama、Custom OpenAI 只是自部署示例。127.0.0.1 在网关容器内指容器自身；连接宿主机或其他服务器必须替换地址，页面已加入提示。所有默认地址仍可编辑。

套餐的独立地址也已填充：智谱全球区、阿里 Coding/Token Plan、腾讯国内及全球区按量/订阅、百度 Coding/Token Plan、方舟旧 Coding 与 Agent/Token Plan、小米 Token Plan、Kimi 国内及海外按量/订阅，以及 OpenCode Go/Zen。默认值集中在 `backend/app/providers/presets.py`。

DeepSeek Responses 使用根地址、Messages 使用 /anthropic/v1；智谱 Coding 的 Chat、Responses、Messages 各有专用地址。选择额外协议时自动填入已知的独立基础地址并展开 URL 区。参考 [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/)、[DeepSeek Anthropic](https://api-docs.deepseek.com/guides/anthropic_api/)、[智谱协议端点](https://docs.bigmodel.cn/cn/coding-plan/tool/others)。自定义地址不会强制替换成官方地址。

图片展示覆盖供应商下拉菜单、当前选中项、列表和详情。本地 SVG 无外部加载依赖，断网仍可显示；18 个品牌图标来自 MIT 许可的 LobeHub 1.95.1，SGLang、Custom OpenAI 使用原创字母标识。许可证和出处在 `frontend/public/providers/`。

## 参数合理性与修复

| 参数 | 规则及验证 |
|---|---|
| 账号名称 | 必填，去除首尾空白，最多 80 字符；已删除同名账号可重新创建 |
| 供应商/账号类型 | 对应实际目录；切换套餐自动填入其专用地址，不混用按量与订阅默认值 |
| 协议类型与配置 | 根据接入方式展示支持的选项，默认仅选择一个可用协议；保留已有历史配置。切换文本、多模态、图片或向量时同步映射类型 |
| 服务 URL | HTTP/HTTPS 完整基础地址；拒绝凭据、查询串、片段、空白、请求端点；版本路径保留 |
| API Key | 云供应商必填；最多 4096 个非空白 ASCII 字符。编辑留空保留原 Key，更换和清除互斥，不回显密钥 |
| 模型映射 | 1–100 条，名称完整且不重复，类型须与账号类别一致；保留模型名称和启用状态 |
| 默认测试模型 | 仅能选择当前账号已启用的映射；修改名称或停用映射后清理无效选择 |
| 保存验证 | 默认关闭，启用账号并指定测试模型后才可使用；会实际调用并可能计费，本轮未执行 |
| HTTP 代理 | 可选，HTTP/HTTPS 地址及端口，不能包含凭据、路径、查询或片段 |
| 优先级 | 0–100000 整数，数值越小越优先 |
| 最大并发 | 1–100000 整数，默认 10，单位为“个请求”；应按上游额度设置，系统总体并发另受全局配置限制 |
| 状态/备注 | 启用或禁用；备注最多 2000 字符 |
| 发现模型 | 使用当前连接配置；切换配置后丢弃旧发现结果，防止模型列表串到另一供应商。列表 API 不可用时允许手动映射 |

修复了不支持 Responses 的接入仍默认显示 Responses、套餐地址为空、类型切换遗留错误映射、发现模型请求结果串配置、代理/整数参数前端反馈不足等问题。

Ollama 原生适配器目前只具备发现模型等基础能力，生成转发和原生 NDJSON 流链路未完整支持。本轮新增账号统一使用已有 OpenAI 兼容端点；不删除原生适配器、不改写历史账号。需要原生协议全链路支持时应单独实施与验收。

## 验证结果与边界

- 隔离实际应用、PostgreSQL、Redis：后端 100 项通过，0 跳过。
- 20 个供应商、39 种套餐：逐个真实 HTTP 新增、读取、删除；地址、类型、优先级、并发、状态、默认测试模型与备注保存一致，Key 不泄露；非法并发、优先级、代理及默认模型返回 422。
- 前端 vue-tsc/Vite 构建通过，18 项 Node 回归通过。
- 隔离浏览器确认默认值及图标布局。部署后再次逐个切换线上 20 个供应商，全部默认地址正确；20 个品牌图标全部加载成功，智谱 Coding Responses 独立地址自动填充正确，无浏览器错误。仅操作未保存表单，未改生产账号；未完成全部写操作的浏览器验收。线上证据在 `.deployment/provider-icons-live.png`、`provider-protocols-live.png`、`provider-ui-results.json`。
- 构建修复镜像 `helidata-ai-gateway:provider-check-20261012`，包含本轮前端与后端，以及上一轮尚未上线的审计修复。
- 修复镜像启动健康，镜像中的后端完整 100 项再次通过（24.915 秒）；最终前端 18 项通过。最终镜像摘要 `sha256:a35f57b4c5ec76c84b70a36ada2d8350f7a60dce67ff1af85740ac54bfc982e8`，镜像内 20 个离线图标及编译后的供应商页面检查通过。
- 未使用真实供应商密钥、未调用上游模型、未产生推理费用。上述结果证明网关参数与保存流程可用，不能证明每个供应商在用户账号额度、地域、网络及模型权限下都能成功生成。
- 各套餐的使用范围以官方条款为准；例如部分 Coding/Token Plan 限定交互式编程工具，不能将具备兼容地址解释为支持任意业务场景。

## 上线安全方案

用户明确授权“现在部署”后，已完成上述上线方案。数据库备份经 pg_restore --list 检查可读，停止旧容器后对整个 data 目录制作保留文件权限和归属的冷备份。替换及启动验证耗时约 29.64 秒，4 个进程均 RUNNING；用户、供应商、API Key、模型组记录数及迁移版本未变，配置和主密钥摘要未变。原数据挂载、18080 端口、环境、restart 策略及 nofile 限制保留，无数据库结构变更。

备份：`/opt/AIGateway/backups/before-provider-20261012T151528`（目录 700、备份文件 600）。停止的旧容器 `helidata-ai-gateway-before-provider-20261012T151528` 及旧镜像已保留供回滚。生产使用本报告的最终修复镜像，`helidata-ai-gateway:v1.0.7` 标签同步指向该镜像，使现有启动脚本仍使用当前修复；未创建新版本标签、未推送 GitHub。
