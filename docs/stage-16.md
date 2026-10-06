# 阶段16：智能路由

日期：2026-10-05，Asia/Shanghai。

本阶段依据开发计划的“阶段16：智能路由”、完整开发提示词及Excel中的D-01至D-04进行。阶段15的真实Provider逐接口验收仍待可用账号配置，不因开始本阶段而视为通过。

## 数据库与检索

- Docker多阶段编译pgvector **v0.8.7**，源码下载SHA256固定为`cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85`。编译关闭本机CPU优化，运行镜像仅复制扩展文件，不包含编译工具链。
- PostgreSQL本地bootstrap以postgres身份创建vector扩展；应用数据库角色保持非超级用户。重复启动使用`CREATE EXTENSION IF NOT EXISTS`，不更换Master Key。
- Migration0012新增`route_configs`、`route_samples`、`route_vectors`和`route_decisions`。配置引用逻辑模型和两个不同的模型组；默认禁用、失败默认报错。TopK范围1至50，相似度和置信差范围0至1，数据库同时保护这些约束。
- 样本按规则及Prompt摘要去重，记录pending/processing/ready/failed/stale状态、失败码与修订号。管理员主动录入的训练样本保存Prompt；请求决策表没有请求正文或生成内容字段。
- 管理输入使用严格整数和有限阈值。批量最多500条；CSV仅接受UTF-8（支持BOM）、`prompt,classification`表头，文件最多2MB，支持引号、逗号和换行，失败信息只报告行号，整批校验后再写入。
- 向量最多4096维，拒绝布尔、非数值、NaN、Infinity、溢出和零向量，应用层归一化以避免float32余弦计算溢出。数据库再次校验维数及非零约束。
- pgvector按余弦距离进行精确TopK查询；只读取ready且样本修订、规则向量版本、Embedding模型和维数均一致的向量。未启用HNSW或IVFFlat，不声称具有近似索引性能。
- 向量完成写入按“规则→样本”顺序短事务加锁，核对任务捕获的Embedding模型、规则向量版本、样本修订及processing状态，向量与ready状态同时更新；过期或重复完成结果丢弃。重新向量化/重试必须递增样本修订，避免旧网络任务覆盖重试结果。
- 分类使用TopK中每个类别最高相似度，领先类别同时达到相似度阈值和置信差。未出现的另一类以0作为基线；跨类别相似度差小于等于1e-7仍视为歧义，空样本和阈值不足返回明确原因。
- 决策使用唯一Request ID，保留虚拟模型、规则ID、Embedding子请求ID、TopK证据、分类、选中组快照和决策耗时。删除规则/样本/模型组不删除历史决策；删除样本会级联删除相应向量。

## 规则、任务与在线链路

四个管理员页面为 `/admin/smart-route`、`/samples`、`/logs`、`/statistics`，接口位于 `/api/admin/smart-route`。规则支持新建、修改、禁用和删除；虚拟模型名不可与普通模型冲突，不能映射上游，目标组须不同、启用且含可用真实模型，禁止递归。普通用户接口返回403，页面重定向。

样本支持单条、批量、CSV、编辑、删除与重新向量化。Migration0013增加请求管理员、任务Request ID及开始时间；后台执行真实HTTP Embedding，失效任务通过版本核对拒绝覆盖。processing超过180秒恢复为新修订任务；失败仅保存错误码，可手动重试。修改Embedding模型使旧向量失效并重新排队。

管理员样本任务占用全局及Provider并发，等待客户端已有队列；这是独立管理工作，不消耗客户端用户组/API Key配额。任务仅允许仍启用的管理员执行，实际Token按管理员和Provider独立记入调用日志和用量。任务最长120秒，并发租约持续续期与释放。

AI-Auto等虚拟模型经用户授权、Embedding子请求、pgvector TopK、相似度与置信差判定后选中简单或复杂模型组。客户端必须同时获得虚拟模型、Embedding模型及两个目标组授权。子请求沿用完整准入、配额及日志链路，在父请求准入前执行，支持并发容量1。目标组内继续使用账号健康、调度和故障转移；生成响应保持虚拟模型名称。

支持文本Chat、Messages与Responses请求；图像、空文本和超限输入给出明确错误。preflight不执行Embedding或推理。fallback可配置报错、简单组或复杂组，记录原因；401/403/409/429/499不得通过fallback绕过权限、配置变更、配额或取消。

决策日志支持时间范围、虚拟模型、Request ID与分页，展示TopK证据并连接父调用和Embedding子调用。统计显示分类命中、结果、目标组、平均决策耗时、相似度及实际上报Token；Token统计只包含父生成调用，Embedding子调用在用量中独立计费。未上报Token保持未知。历史快照在源配置删除后保留。

## 验收与生产边界

核心7组验收使用真实Nginx/FastAPI/PostgreSQL/Redis及可控HTTP上游夹具，覆盖样本任务、两类路由、实际用量、容量1、流式、撤权、失败fallback、无效向量重试、取消、配置变更、配额禁止绕过、中断任务恢复、级联及历史。夹具提供合成Embedding与生成结果，不代表付费供应商验收。

浏览器验证规则保存、样本重新向量化、决策TopK、Embedding子日志到父日志、统计到用量筛选及普通用户重定向。截图 `stage16-decision.png`、`stage16-statistics.png` 中的数据属于随后清理的隔离环境。迁移测试使用独立Stage15卷升级及全新0700卷，检查原用户和Master Key摘要、六种操作日志/用量保持及迁移往返。

最终构建、回归和部署结果见 `stage16-validation.txt`。目前没有启用的真实Provider，阶段15逐接口及阶段16真实供应商调用验收仍待配置；不开始阶段17。

## 升级与回滚

升级前备份 `/data/backup/stage16-before-upgrade.sql`。应用0.16.0、health phase16、Migration0013、pgvector0.8.7；沿用原/data、用户和Master Key。

降级0012删除任务元数据字段；降级0011进一步删除阶段16四表及全部规则、样本、向量和决策数据，但保留扩展、逻辑模型与阶段15事实。需要保留阶段16数据时先备份并恢复完整数据库，不能依赖降级保存样本。迁移往返验收只操作一次性卷。

pgvector来源及算法依据：[官方文档](https://github.com/pgvector/pgvector)。基础验收历史保存在 `stage16-foundation-validation.txt`。
