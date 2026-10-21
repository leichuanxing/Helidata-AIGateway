# 自定义接入文生图与重排序（2026-10-21）

复用现有OpenAI兼容协议适配器，为OpenAI、vLLM、SGLang、Ollama及Custom OpenAI五类接入开放openai-images和openai-rerank；账号类型选项及能力说明由同一后端目录驱动，前端无需新增协议模块。

修复OpenAI/Ollama兼容接入的适配器选择，并为Ollama兼容接入开放两类operation。Ollama原生协议仍不被冒充为Images或Rerank，必须明确选择对应OpenAI兼容协议，且上游确实提供/images/generations或/rerank。模型能力以部署服务实际接口为准，开放选项不表示默认官方OpenAI端点或普通文本实例支持这些能力。其他供应商及套餐限制保留。

不自动修改已有账号、密钥、模型映射或地址。沿用现有模型授权、并发、合规、调用日志及负载均衡实现。无需数据库迁移（保持0034）。

验证：供应商预设6项、前端40项通过。新增隔离矩阵覆盖5类接入×2种操作的账号保存、真实HTTP转发、模型名称映射、API Key、日志及负载均衡路由，10种组合全部通过。完整后端131项中130项通过、1项跳过（长耗时专项）；既有全供应商路由矩阵已扩至17种组合并通过。测试只使用回环上游和虚拟凭据，不代表每个实际部署实例或官方云端模型已验证，不产生真实供应商费用。

用户已授权后续直接部署：通过验证后备份数据库及完整卷，保留旧容器，替换固定镜像，健康检查失败回滚。不推送GitHub。


生产部署完成：镜像 sha256:8659eafa6c17d617b3fc6edef1d929b06f7a3c3f1ba02fa5ec63183f82c7279d。数据库0034，四个Supervisor进程RUNNING，nginx配置检查成功。生产目录接口确认五类接入均含两种协议，账号143/144仍启用，对话测试模型目录正常。备份：/opt/AIGateway/backups/before-custom-operations-20261021T113541Z；回滚容器：helidata-ai-gateway-before-custom-operations-20261021T113541Z。未推送GitHub。
