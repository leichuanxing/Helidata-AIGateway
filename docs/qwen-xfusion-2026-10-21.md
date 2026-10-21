# qwen3.5-0.8b 接入与测试（2026-10-21）

账号144，名称保留用户修改的192.168.32.105，供应商类型vLLM，模型映射qwen3.5-0.8b。最终基础地址：http://192.168.32.105:3080/serving-gateway/a12640e223854bfcbfd893bb68854bb3/v1。保留用户其余配置，无应用代码修改或生产重启。

最初HTTPS地址因缺少受信任xFusion CA而失败，未关闭证书验证。随后用户提供HTTP3080地址，按其明确指定的新地址接入。检查发现用户修改的账号地址缺少/v1，保存密钥与其明确提供的单个密钥格式不一致；修正地址，并用用户提供的单个密钥加密保存，未记录密钥内容。OpenAI和Anthropic均使用Bearer Token；该服务的x-api-key方式未通过，已改为验证成功的Bearer。

最终直接上游真实测试（Reply with OK only，max_tokens=64）：
- Chat非流式：HTTP200，OK，320ms。
- Chat SSE：HTTP200，OK，234ms，收到[DONE]。
- Anthropic Messages非流式：HTTP200，OK，236ms。
- Anthropic Messages SSE：HTTP200，OK，235ms，收到message_stop。

正式网关Chat入口验证：
- 非流式 req_8068d999f8524d0187619247352b50e4：HTTP200，日志success，实际账号144，总Token19。
- SSE req_1dfa32ba53714aa68d9fe75359bcec6e：日志success，HTTP200，实际账号144，总Token19，已收到[DONE]。流结束后即时读取日志曾返回404，异步落库后重新只读核对成功，没有为日志查询重复发起推理。

最终读取账号状态enabled、health_status=healthy、配置版本6；对话测试目录该模型configured=true。全部管理员验证会话已退出。本次未创建新的网关API Key，因此Anthropic网关公开入口未单独跑完整API Key链路；原生上游协议已实测。图片、工具调用与更长上下文不在本次测试范围。

早期测试脚本的普通响应解析有NameError，已修正并重新取得上述真实成功结果，没有把脚本错误作为模型故障结果。初始上游500/401结果不代表修正后的当前状态。不推送GitHub。
