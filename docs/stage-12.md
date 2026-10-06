# 阶段 12：调用日志与 Request ID

2026-10-05（Asia/Shanghai）部署应用0.12.0、镜像helidata-ai-gateway:stage12、Migration0008。访问 http://192.168.31.97:18080，管理员菜单“调用日志”，路径/admin/call-logs。阶段8/9的Chat调用方式及阶段10/11的调度、并发、队列、配额继续适用。

## 持久化终态与链路

新增call_logs，每个服务器生成的Request ID最多一条终态记录，数据库唯一约束及ON CONFLICT保护重复写入。保留原运行日志allowlist；Request ID继续贯穿响应头、JSON/SSE错误、Pipeline、HTTP/Nginx日志和每次上游HTTP请求。客户端提供的X-Request-ID不会替换服务器ID。

覆盖模型目录、预检、Chat非流式及SSE。认证失败、权限/配额/队列拒绝、请求格式校验和上游失败也记录。Chat和预检在进入Pipeline之前的格式错误通过中间件补记安全元数据，不保存错误请求正文。非流式释放资源和数据库连接后写入；SSE由响应资源所有者在实际成功、流中失败或取消后写入，获取响应头不视为成功。

| 字段 | 口径 |
| --- | --- |
| request_id、created_at、operation | 服务器ID、Context建立时间（UTC存储）、models/preflight/chat |
| user_id、user_group_id、api_key_id、client_ip | 已识别的身份ID和ASGI客户端IP，未认证身份为空 |
| username_snapshot、group_name_snapshot、key_name_snapshot | 身份名称历史快照；不保存Key明文或Hash |
| protocol、request_model、logical_model、upstream_model | 所选账号协议、请求模型、已选逻辑模型、上游映射名称；未选模型为空 |
| provider_id、provider_name_snapshot、stream | 所选账号ID/名称及流式标志 |
| status、http_status、error_code、error_message | success/failure/client_cancelled、Gateway状态、脱敏错误码与通用诊断信息 |
| input_tokens、output_tokens、cached_tokens、total_tokens | 有效上游usage的prompt/completion/cache/total值；未上报为空，绝不使用预算假装实际Token |
| gateway_latency_ms、upstream_latency_ms | Pipeline到终态记录前耗时，以及实际上游尝试耗时合计；包含重试/流式等待，排除日志入库耗时 |
| ttft_ms、tokens_per_second | 本阶段为空，阶段13采集；没有虚构0或估计值 |
| trace | 有序阶段、认证状态、授权模型组快照、尝试链、入场等待耗时、SSE事件数及后续功能状态 |

尝试链保存每个账号候选的ID、名称、协议、配置版本、逻辑/上游模型、结果、错误码、可得的上游HTTP状态和真实尝试耗时。未发送候选不伪造上游HTTP状态；超时/网络错误可能没有上游状态。失败切换和最终成功使用同一Request ID，可看到两次实际走向。阶段标签表示到达相应步骤，不保证该步骤成功；资源预留失败同样能定位并发步骤及错误码。

SSE响应头发送后发生错误或取消，http_status仍为200，以status/error_code判定终态；响应头前客户端取消记499。客户端断开不产生第二条成功记录。有效累计usage以最后有效值为准，不逐帧累加，后续异常usage不抹掉已知有效用量。一次调用的顶层usage对应最后执行尝试；未知的前次成本继续由阶段11未上报预算管理，不能推算成实际Token。

日志通过历史标量ID与名称快照关联，源用户/组/Key/Provider删除不会级联删除历史调用。关联账号仍存在时可打开详情；已删除时返回不存在，日志快照继续可读。

## 数据库故障与待写目录

独立短事务插入，最长等待3秒。失败后将经过allowlist的终态写到/data/logs/call-log-outbox，目录gateway:gateway权限700、JSON文件600，原子替换并fsync文件与目录。启动脚本明确授予gateway对日志父目录的遍历权限，不改变其他日志文件所有权。

后台每5秒重试，每批最多100条；成功插入才移除待写文件。数据库唯一Request ID使重放安全，重启保留未写记录。持久化失败不把已成功生成的响应改成错误；运行日志会记录“deferred to durable outbox”。数据库和磁盘同时不可写会明确报告存储失败，不能保证这类故障无日志丢失；进程在终态记录前崩溃也不保证存在完整终态。此阶段没有日志保留期限配置或自动清理业务记录。

## 查询、详情及权限

| 接口 | 用途 |
| --- | --- |
| GET /api/admin/call-logs | 管理员分页组合查询 |
| GET /api/admin/call-logs/{request_id} | 管理员读取完整调用详情与trace |

查询参数：request_id（精确）、user_id、user_group_id、api_key_id、provider_id、model（请求/最终逻辑模型精确）、status、http_status、error_code（精确）、operation、start、end、page、page_size。status=failed匹配失败和客户端取消。默认最近7天，自定义时间需含时区且跨度不超过31天，范围为[start,end)。page_size最多100，page最多10000；Request ID精确查询且未指定时间时可查更早记录。SQL参数绑定，注入样式字符串不会扩大查询。

超级管理员和管理员可查询；普通用户403，未登录401，第一登录未改密仍受原权限门禁。详情不存在或请求尚未结束返回404 CALL_LOG_NOT_FOUND，待写期间也可能暂时不可查。不存在普通用户可绕过权限的日志接口。

页面支持全部筛选、分页、刷新、“仅失败与取消”、Request ID进入详情和返回精确查询。详情分基本信息/认证、模型/账号、链路/Failover、Token/性能、错误/智能路由/内容审核，使用历史快照。账号详情联动失败日志，用户详情联动该用户日志；查询条件保存在URL，支持直接链接。智能路由阶段16、审核阶段17如实标记未启用。预检/目录列表不把未生成的调用显示为Token消耗。

仅保存结构化身份和调度元数据，原始messages、Prompt、图片、工具参数、生成内容、Authorization、API Key、密码、Hash、上游URL和代理凭据不入库或待写目录。上游真实模型及账号名称仅用于管理员排障，普通用户不能获取。错误信息不保存上游原始错误文本。

## 验收、升级和范围

验证记录见stage12-validation.txt。实际Nginx/FastAPI/PostgreSQL/Redis/HTTPX夹具验证成功/失败/认证/校验、500账号切换、SSE成功/错误/取消、组合筛选和权限、26并发推理/查询、重启持久化、账号改名及删除快照。注入数据库日志存储失败后实际落盘并重放；以gateway运行用户验证700/600权限及真实数据库写入。流式、非流式、调度、Core、四级并发/队列/配额回归、新0700数据卷启动全部通过。

最终容器13个真实流式取消逐条比对运行日志及call_logs：唯一终态，12个SSE200和1个响应头前499。前端Vue/TypeScript/Vite及Docker构建、Python编译通过。浏览器验证列表/失败筛选/详情/返回精确查询和退出登录，截图stage12-logs.png、stage12-detail.png仅包含已清理的验收夹具。

升级前备份/data/backup/stage12-before-upgrade.sql。0007→0008新增日志表和索引，未重置管理员或替换Master Key。原用户及密码状态摘要保持；生产Gateway配置恢复500/1000/30/300；已确认的测试调用、临时身份/Provider/配额/Redis占用、隔离容器及卷清理，其他应用健康。当前启用真实上游账号为0，不能声称真实付费生成已验收。

按开发计划完成阶段12后停止。下一阶段：阶段13 Token、TTFT、Tokens/s与用量统计；Dashboard属于阶段14。
