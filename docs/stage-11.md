# 阶段 11：四级并发、等待队列与配额

2026-10-05（Asia/Shanghai）部署应用0.11.0、镜像helidata-ai-gateway:stage11、Migration0007。访问 http://192.168.31.97:18080。Chat与SSE调用方法沿用阶段8/9，调度沿用阶段10；本阶段替代历史文档中并发、队列和配额尚未实现的说明。

## 四级并发和队列

Redis Lua一次检查并占用Gateway、User Group、API Key、Provider四级名额。计数表示正在执行的请求，不是QPS。等待请求不持有部分名额，不提前访问上游；预检不占名额、不排队、不预留Token预算。

所有请求进入共享FIFO队列，只有队首且四级均有容量时才能执行。队列满或queue_size=0返回429 QUEUE_FULL；累计排队时间超过queue_timeout返回429 QUEUE_TIMEOUT。严格FIFO可能出现队首受某个账号或组限制、后面其他请求也暂时等待的情况。排队期间每约0.25秒重查Key、用户、组及授权，轮询客户端断开；撤销Key不会让旧等待请求继续执行。

并发与等待所有权有效期90秒，执行中每20秒续租，Redis服务端时间用于过期判断。结束、错误和客户端取消清理自有令牌；续租失败取消执行，503 CONCURRENCY_UNAVAILABLE，不冒充客户端取消。Redis不可用时即时清理可能失败，遗留名额由期限回收。SSE持续持有到真正结束。非流式也主动监听客户端断开并取消上游。

首次原子预留的Provider名额交给调度器继承，避免重复占用。失败切换账号后仍受账号级限制；所有剩余候选都满载时释放外层名额并重新排队，再次同时占用四级。沿用候选次数、调度期限、健康冷却和流式响应开始后不重试的边界。

生产配置已恢复：max_concurrency=500、queue_size=1000、queue_timeout=30、stream_idle_timeout=300。配置来源为/data/config/config.yaml；修改Gateway配置后重启Uvicorn生效，监听端口等基础配置仍需重启整个容器。Nginx读取超时310秒，应与排队和上游期限协调。

## 共享配额及真实用量

配额由用户组内所有用户和API Key共享，quota_limit=0表示不限。daily、monthly以Asia/Shanghai（UTC+8）的日期/月划分，permanent使用永久桶。每次上游尝试开始时固定周期；跨午夜结束仍结算到该尝试的原周期。切换周期保留旧记录。Migration0007新增quota_buckets与quota_reservations，预算和已知用量持久化到PostgreSQL，重启不会清零永久配额。

每次尝试先事务锁定并预留预算，剩余预算不足返回429 QUOTA_EXCEEDED，不发送上游。预算包含请求JSON UTF-8字节及输出上限乘n；有限配额下n限定1–128。未指定输出上限时默认预估1024，有限配额会按剩余预算缩小并传递max_completion_tokens。并行预留不能花用同一份剩余预算。

这是保守预算估计，不是通用Tokenizer。它可能在仍有实际Token余额时提前拒绝较大的请求；多模态或特殊上游计量也可能超出估计。有效usage.total_tokens按上游实际值完整记录，不能因超出预估截断，后续请求按新的余额拦截；不承诺单次请求绝对不会超额。流式usage为累计值，保留最后有效值，不累加每帧或伪造Token。

统计严格区分reported_tokens（已上报实际Token）、reserved_budget（执行预留）和unreported_budget（未上报预算）。缺少usage、取消、上游可能已受理的错误/超时均不能假装免费，也不能把估计预算写成实际Token。明确拒绝请求的HTTP400/401/403/404/422/429释放本次预算；不确定结果保留为未上报预算。重试的每个尝试独立预留、结算。

持久化预留90秒、每20秒续期。崩溃留下的过期预留转为未上报预算，不自动退款；查询和新请求会触发恢复。管理员应核对上游真实用量后再核销。核销记录实际Token并写审计，重复核销返回409，普通用户无此权限。有限配额可能因未上报预算而暂停接入，直到核验完成。

## 接口与页面

| 接口 | 权限与行为 |
| --- | --- |
| GET /api/admin/resource-status | 管理员读取实际执行数、排队数及配置；Redis故障503 |
| GET /api/portal/quota | 当前启用用户读取所属用户组共享配额 |
| GET /api/admin/user-groups/{id}/quota-reservations?page=1 | 管理员分页读取未上报预算，50条/页 |
| PUT /api/admin/user-groups/{id}/quota-reservations/{reservation_id} | 管理员提交reported_tokens核销，事务与审计保护 |

用户组管理接口新增quota_usage，页面展示实际Token、未上报预算及剩余预算，不限配额显示“不限”。前端完成Vue/TypeScript/Vite构建，真实管理接口字段与保存行为已验收；本阶段未新增浏览器视觉验收。业务调用日志表属于阶段12，统计页面属于后续阶段，当前终态调用日志仍写运行日志。

## 验收与数据保留

详细证据见stage11-validation.txt，真实Nginx/FastAPI/PostgreSQL/Redis/HTTPX夹具验收覆盖四级容量、FIFO、队列满/超时、取消和动态权限、周期及并行配额、SSE用量、崩溃恢复与管理员核销。调度、非流式、流式、Core、用户组/API Key及0700新数据卷启动均通过。修复event:error携带[DONE]误判为成功的边界并复测流式；最终容器13条真实流式取消逐条验证只有一次client_cancelled终态。

升级前备份/data/backup/stage11-before-upgrade.sql，原用户及密码状态摘要一致，Master Key保持。测试用户、Provider、配额记录、临时容器和卷已清理，生产配置恢复，其他已有应用健康。当前启用真实上游账号为0，所有生成验收使用真实HTTP协议夹具，付费模型生成仍需录入实际账号后验收。

按分阶段计划完成阶段11后停止，下一阶段为阶段12调用日志与Request ID。
