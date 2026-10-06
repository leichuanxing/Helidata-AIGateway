# 最终测试说明

验收使用实际Nginx/FastAPI/HTTPX/PostgreSQL/Redis和本地HTTP协议服务器；协议测试服务器是独立测试设施，应用路径没有替换成Mock。内容审核使用固定真实ONNX模型及pgvector。数据卷为/opt/AIGateway/.deployment下的UUID独立目录，不挂生产卷。容器和数据用finally清理；UI验收短时独立发布18081。

| 验收领域 | 脚本/证据 | 结果 |
| --- | --- | --- |
| 登录、Refresh、限流、角色、用户 | stage3_acceptance.py | 通过 |
| 用户组、模型授权、API Key | stage4_acceptance.py、stage6_acceptance.py | 通过 |
| Provider加密、代理、模型映射 | stage5_acceptance.py、stage6_acceptance.py | 通过 |
| Chat、SSE、原生Responses/Messages/Embeddings/Rerank/图片、转换 | stage15_translation.py、stage15_acceptance.py | 通过隔离实际HTTP |
| 配额、并发、Queue、Failover、取消与超时 | stage13_resource_regression.py、stage13_streaming_regression.py、stage13_acceptance.py | 通过 |
| 调用终态、幂等/补偿、用量、Dashboard | stage13_acceptance.py、stage14_acceptance.py | 通过 |
| 智能路由、实际上游Embedding及pgvector | stage16_core.py | 最终镜像专项验收通过 |
| 内容审核、Audit/Block、本地ONNX、证据 | stage17_acceptance.py | 通过 |
| 共享HTTP池、安全、压力、45秒SSE、依赖故障 | stage19_security_load.py | 通过 |
| 设置角色/冲突/热更新/PNG、正文脱敏/清理 | stage20_settings.py | 通过 |
| 容器重启与删除后重建同一/data | stage20_persistence_host.py | 通过 |
| 备份实际dump/restore、文件限制、审计 | stage20_operations_regression.py | 7组通过 |
| 旧0014→0017、降级/再升级、初次启动 | stage20_migration.py | 通过 |
| 实际浏览器CSP、品牌、四设置Tab、图表及文本XSS | docs/stage-20.md及截图 | 最终浏览器验收通过 |

首次组合回归的业务/压力/设置部分全通过；最后备份审计测试误把先前测试其他管理员的事件算入自己的身份断言。已将测试按actor_id限定，并在最终镜像独立复验7组全部通过。该修正不更改应用权限或放宽身份校验；原失败记录保留用于解释组合测试退出码。

## 压力边界

最终候选实测：100客户端100成功，6.456秒；500客户端500成功，33.890秒；1000客户端578成功、422受控429，41.438秒；复测100客户端100成功，7.108秒。没有5xx。1000是客户端同时提交数量，不是1000个实际同时执行的上游请求。429来自独立准备队列30秒时限，容量不能被无限排队掩盖。

加载真实ONNX后的进程RSS起始563620KiB，稳定后620320KiB；HTTP文件描述符从25稳定到26，收敛后24。该内存范围包含模型，不能与未加载ONNX的阶段19约180MiB直接比较。45秒SSE经历两次租约续期，3次真实取消后HTTP活跃租约/四级并发归零、准备等待为0。1700个唯一Request ID均有持久调用日志。只证明本次短时测试，无长期泄漏结论。

## 可复验方式

在构建好候选或最终镜像的Linux主机、项目根目录执行host脚本。stage20_host默认候选镜像，stage20_final_host使用最终镜像专项测试；stage20_migration需要保留stage17镜像以生成真实旧数据。stage20_persistence_host可通过STAGE20_IMAGE指定固定最终镜像。STAGE20_UI=1使用18081并等待验收释放标记，不可与其他UI测试争用该端口。

不可直接`docker exec`生产运行验收：测试会创建/删除测试账号和业务对象、改设置、停止Redis/PostgreSQL、模拟故障。旧阶段脚本的旧head或旧页面断言仅用于历史版本，最终入口脚本明确选择兼容测试。

本次未获付费调用授权前不使用现有真实Provider做推理。真实供应商Chat/SSE及每个扩展协议/智能路由Embedding的端到端适配、供应商限额和费用验收应在明确授权后执行。隔离功能通过不等于所有供应商支持所有原生协议。最终交付保留这项验收边界，生产只做不产生推理费用的健康/结构/配置验证。

新增stage20_release_smoke.py以最终完整镜像验证Nginx的/openapi.json JSON路由、版本、CSP、公开设置和健康。发布检查曾发现该路径误返回SPA页面，已补充精确代理并隔离复验；失败版本的生产数据已经按冷备份完整回退后重新发布。
