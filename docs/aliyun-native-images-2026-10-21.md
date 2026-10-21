# 阿里云文生图 404 排查与原生适配（2026-10-21）

## 问题与证据

线上账号 143（文生图），模型 qwen-image-3.0-pro，地址 https://dashscope.aliyuncs.com/compatible-mode/v1。最近三次请求的 trace 均为上游 HTTP 404，包括管理员账号测试和对话测试；内容合规未命中。不是模型目录显示或合规阻断问题。

空文本诊断：同一官方域名 /compatible-mode/v1/images/generations 返回 404；/api/v1/services/aigc/multimodal-generation/generation 返回 400 InvalidParameter（text 为空），证明原生端点存在且参数校验正常。密钥未输出、未发送到其他主机。

官方资料：
- https://help.aliyun.com/en/model-studio/qwen-image-generation-and-editing-api-reference
- https://help.aliyun.com/zh/model-studio/qwen-image-3-0-pro

用户允许付费后，沿用此前人民币 1 元上限，只发起一次原生真实生图：一张 1024×1024，无输入图片，无自动重试。HTTP 200，耗时 47.84 秒，返回 output_image_count=1，output_image_type=qima_output_1k，request_id=4693d21e-7149-9c0c-8c04-d0b01de305d0。北京区官方原价 0.25 元/张，实际扣款/免费额度以阿里云账单为准。本次没有下载远程生成图片，也未将其充当隔离测试结果。

## 修复

- 阿里云账号明确填写 /api/v1 时，使用原生同步文生图接口。模型限千问 3.0 / 2.1 系列。
- 仅转换支持的参数：prompt 到 input.messages，n 和扩展参数到 parameters，尺寸 x 转为 *；auto 使用上游默认。未知参数、b64_json、图生图及不支持的数量在调用前拒绝。
- 将 output.choices 图片 URL 转为标准 Images data；保留图片 usage 和 request_id，不虚构 Token。
- /compatible-mode/v1 保持兼容接口行为；不会收到错误后尝试另一个生图端点，避免重复计费。
- 新增文生图账号默认原生 /api/v1，接入说明同步更新。其他协议和已有账号配置不自动修改。

## 验证

本地真实回环 HTTP 原生转换、参数拒绝、错误不重试、兼容模式保留测试通过；供应商预设 6 项及分页发现 1 项通过。完整链路隔离回归结果待补充。

## 上线方案与边界

本次尚未部署。需备份数据库、完整数据目录并保留旧容器，部署后通过管理员接口将账号 143 地址改为同源 /api/v1（核对配置版本后修改）。保留密钥、模型、授权及端口。失败回滚容器和数据。预计重启中断 30–60 秒，不推送 GitHub。真实供应商调用已验证原生接口；部署后管理员入口未完成真实生图验收。

隔离容器完整 HTTP 回归：3 项，2 项通过、1 项显式 185 秒专项跳过，耗时 5.441 秒。覆盖原生及兼容接口、管理员生图、API Key、同名重建、合规拦截、负载均衡、失败单次调用及日志。候选镜像 sha256:3c5fa72995d017f2ac0b74e2bb53dc6610d8ce8474715532f9f10a35bbbc66c4。

## 2026-10-21 生产部署

用户明确批准“现在部署并修正地址”。固定候选镜像 3c5fa72995d017f2ac0b74e2bb53dc6610d8ce8474715532f9f10a35bbbc66c4 已上线，容器健康、数据库版本0033，登录页/管理页面/健康接口返回200。

备份：/opt/AIGateway/backups/before-aliyun-native-images-20261021T054136Z（SQL、完整停止后数据卷、容器配置）。保留旧容器 helidata-ai-gateway-before-aliyun-native-images-20261021T054136Z。未触发回滚。

通过管理员API并携带 expected_config_version=1 将账号143地址改为 https://dashscope.aliyuncs.com/api/v1。随后重新读取详情，确认配置版本2及原文生图模型映射。密钥未提交更换字段。第一次验证脚本错误地期望 PATCH 精简响应包含 models，地址保存成功后停止；未发起生图请求。修正为 GET 详情核对后继续验收。

正式入口真实验收通过：POST /api/admin/chat-test/images，HTTP200，1张1024×1024，耗时54.95秒，output_image_count=1 / qima_output_1k；Request ID req_349ff9a734c7432db89aae1136546b9a。日志状态success、实际账号“文生图”、上游HTTP200、total_tokens=null；本次无适用合规策略。管理员验收会话已退出。

本轮共两次真实生图（直接原生诊断一次、上线正式入口一次），均各1张1K图片。按北京区官方原价合计约0.50元，未超过授权1元，实际扣费以供应商账单为准。无自动重试。线上完整API链路已验证；本轮未重新执行浏览器图片预览验收。

部署后核对镜像摘要一致、容器healthy；Supervisor确认nginx、uvicorn、PostgreSQL、Redis均RUNNING。不推送GitHub。
