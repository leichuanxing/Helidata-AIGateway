# 自动协议地址显示核对（2026-10-12）

红框中的字段是每个协议的 API 基础地址，不是额外的模型请求参数。当前适配器直接拼接操作路径（例如 /messages），而 Anthropic SDK 会追加 /v1/messages，所以本项目的 Anthropic 地址包含 /v1。删除内部地址会导致多协议请求被发送到错误端点。

已核对供应商目录及自动地址生成方式；20 个供应商中仅不同协议确有不同地址的套餐需要独立地址，其余共用服务 URL。删除普通供应商表单中的重复地址行及自动匹配提示，后台地址生成、保存及请求转发保持一致；Custom OpenAI 仍可配置独立地址。既有账号不自动修改。

核对来源：
- 智谱中国 Coding Plan：https://docs.bigmodel.cn/cn/coding-plan/quick-start 、https://docs.bigmodel.cn/cn/coding-plan/tool/others
- 智谱国际 Coding Plan：https://docs.z.ai/devpack/quick-start
- DeepSeek Anthropic：https://api-docs.deepseek.com/guides/anthropic_api/
- 阿里云套餐地址：https://help.aliyun.com/zh/model-studio/base-url
- 腾讯个人套餐：https://cloud.tencent.cn/document/product/1823/130060
- 腾讯国际套餐：https://intl.cloud.tencent.com/jp/document/product/1300/81489
- 百度 Coding：https://bce-cdn.bj.bcebos.com/p3m/pdf/bce-doc/online/LS/LS.pdf?timeStamp=1749600000081
- 小米：https://mimo.mi.com/docs/zh-CN/tokenplan/integration/tools-overview
- OpenCode：https://opencode.ai/docs/zen/

智谱 Chat、Responses、Messages 使用不同官方地址，Responses 的 /api/v1 是 Coding Plan 官方列出的端点，不能因没有 coding 字样判定为错误。仅隐藏自动配置的表单显示，不删除实际需要的连接配置。

本次为前端显示调整，无数据库迁移、无账号配置修改，不调用真实收费模型，不推送 GitHub。

生产构建及 21 项前端测试通过。已无重启更新线上静态文件，保留旧首页文件及旧哈希资源供回退，浏览器确认智谱 Coding Plan 不再显示红框中的协议地址行。可重建镜像 helidata-ai-gateway:protocol-url-display-20261012 已生成；v1.0.7 本机镜像引用更新，数据库及后台进程未变动。
