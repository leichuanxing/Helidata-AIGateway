# 阶段 9：SSE Streaming 与客户端断开

2026-10-04 已部署应用 0.9.0、镜像 helidata-ai-gateway:stage9；数据库仍为 Migration0006。非流式接口继续可用，基础接口与配置见 stage-8.md；其中 stream=true 的历史限制由本阶段替代。

## 调用与响应

POST /v1/chat/completions 的 stream=true 经同一认证、授权、逻辑映射与 OpenAI 兼容 Adapter，使用 HTTPX AsyncClient.stream 与 FastAPI StreamingResponse 转发。上游请求改写真实模型名，每个响应 chunk 恢复客户端逻辑名；delta、工具调用增量、reasoning 扩展、finish_reason、usage 和其他有效字段保留。stream_options 等 JSON 扩展继续透传。usage 末帧允许 choices=[]，网关不编造 Token 用量。

```bash
export GATEWAY_URL=http://192.168.31.97:18080
# GATEWAY_API_KEY 来自用户创建 Key 的首次显示；逻辑名称需先配置并授权。
curl -N "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"你好"}],"stream":true,"stream_options":{"include_usage":true}}'
```

收到一个完整 SSE 事件后立即验证并转发，不等待整条回答。TCP 包、HTTP 读取块和完整 SSE 事件并不总是相同边界；解析器只缓存当前事件，最多 1MiB，支持跨块 UTF-8/CRLF、LF/CR、首行 BOM、多行 data 和注释心跳。帧规范化后发送，不原样暴露上游注释。成功只在收到上游 [DONE] 时发送 data: [DONE]；EOF 不等同于成功。

Nginx /v1 使用 HTTP/1.1、关闭 buffering/cache、读取超时310秒。HTTPX 保持 TLS 校验、显式代理、不使用环境代理、不跟随重定向。连接/写入/连接池等待10秒；流式读取空闲期限使用 gateway.stream_idle_timeout，当前300秒。流式没有非流式120秒的整条响应期限。没有上游事件时不伪造文本或 Token。

## 错误与生命周期

上游响应头之前的失败返回统一 JSON：鉴权失败502、限流503、超时504、其他网络/格式失败502，输入/权限错误保持原接口行为。已发送 SSE 响应头后不能改 HTTP 状态；解析失败、上游 error、超大事件、超时、网络断开或缺少 [DONE] 会发送 event: error 与脱敏 error 对象，包含 type/code/message/request_id，不附带成功 [DONE]。

资源栈把用户/账号资源租约、HTTPX Client 和上游流连接一起交给 StreamingResponse 持有，在成功、失败、客户端断开及任务取消时关闭。关闭过程屏蔽取消，保证清理完成。等待上游响应头和消费响应体期间均监听 http.disconnect；即使 ASGI2.4 且上游处于空闲，也及时取消上游，而不等待下一块数据触发写入失败。数据库事务在访问上游前提交，响应迭代器不依赖已退出的 DB Session。

终态只记录一次，使用服务器 Request ID 关联；客户端断开记为 client_cancelled。运行日志记录耗时和有效 chunk 数，不记录输入、Key、真实模型名或上游正文。HTTP状态200只能说明流式响应已开始，实际终态以调用日志为准。

当前并发 acquire 仍为阶段11预留接口，本阶段验证租约生命周期与连接释放，不声称已执行四级并发限额。完整健康调度/Failover 为阶段10；流式中途不重试、不重复发送已输出内容。业务日志表/统计、配额和合规等继续按计划实现。

## 验收与部署

tests/stage9_acceptance.py 使用真实 Nginx/FastAPI/PostgreSQL/HTTPX 和临时 HTTP 服务验证分段到达及实际 curl -N；UTF-8/CRLF/BOM/多行解析、工具调用和 usage；响应头/流中错误与 EOF；12次收到部分内容后在空闲期间取消，以及1次等待响应头时取消。另对 ASGI2.4 与真实上游连接验证 DB Session 已关闭、租约持续持有、成功/取消/异常/空闲超时后的释放，终态日志只有一次。验收夹具只存在于测试文件，应用没有模拟生成回答。

tests/stage9_nonstream_regression.py 验证阶段8非流式能力；tests/stage8_core_regression.py 验证统一错误/权限/请求ID及日志脱敏；tests/stage9_startup.py 验证严格0700新数据卷初始化。以上均通过，取消请求的13条生产进程日志也按Request ID逐条核验。记录见 stage9-validation.txt。

部署地址 http://192.168.31.97:18080，健康phase9；备份 /data/backup/stage9-before-upgrade.sql。原用户密码状态摘要一致，Master Key保留，临时测试数据和隔离启动容器已清理。当前没有启用的真实上游账号，因此实际付费模型生成/流式仍待配置真实账号后验证。本阶段交付后停止，下一阶段为阶段10账号调度、故障转移与健康检查。
