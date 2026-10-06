# 系统状态

当前应用版本：v0.1.2；数据库迁移版本：0024。生产主机192.168.31.97，源码目录/opt/AIGateway，正式入口18080，容器helidata-ai-gateway。当前镜像以正式容器与发布备份 manifest.json 为准。

前端提供模型供应商、模型组、用户/用户组、模型广场、个人API Key、用量/调用日志、智能路由、内容合规、系统设置及备份运维。登录页采用居中卡片，支持现有明暗主题和角色跳转。概览顶部仅展示时段和刷新控件，统计卡片直接位于控件下方。Token、请求、并发及失败趋势采用平滑曲线和圆润线条，采样点及缺失数据断点保留。全量产品复刻尚未完成，后续功能差距见product-reproduction.md；原始开发提示词、分阶段计划与Excel需求保留。

## 账号协议配置

新增、编辑账号支持 openai-completions、openai-responses、anthropic-messages 多选及独立路径前缀，Anthropic 支持 x-api-key / Bearer Token。服务 URL 与路径前缀拼接后追加固定协议端点；旧账号未配置 protocol_config 时保留原地址与协议转换行为。原生 Ollama 单独配置。仅勾选服务实际支持的协议；供应商既有操作限制继续生效。

默认测试模型从已启用映射选择，可清空。连接测试通过 GET /models 检查上游模型是否存在，不产生生成调用；模型改名同步更新默认值，禁用或删除映射时清除默认值。模型列表不提供该模型时不能据此断言生成失败。

## 智谱供应商

| 类型 | 默认Base URL | 当前接入 |
| --- | --- | --- |
| 智谱开放平台 | https://open.bigmodel.cn/api/paas/v4 | OpenAI兼容Chat/SSE、嵌入、图像生成 |
| 智谱 Coding Plan | https://open.bigmodel.cn/api/coding/paas/v4 | OpenAI兼容Chat/SSE |

分别填写对应账户/套餐API Key及账户实际可用的模型名称。密钥加密保存，不返回明文。两个接入均未配置独立Responses端点，路由会过滤该操作。模型发现/连接检查执行GET /models，上游不提供此接口时手动配置映射；检查不会自动发起生成请求。Coding Plan使用范围与套餐规则见[官方说明](https://docs.bigmodel.cn/cn/coding-plan/quick-start)，开放平台见[官方API文档](https://docs.bigmodel.cn/cn/api/introduction)。

## 智能路由

对照[产品手册](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/smart_route/)提供样本管理、决策日志、统计和路由规则。支持按行批量添加及CSV导入（可选阈值/备注列）、单样本阈值、显式构建队列、选中/全部构建、预览后添加样本。未构建或过期向量不参与匹配。

已就绪且版本有效的精确样本匹配属于本地规则，不请求向量服务；其余使用向量检索和既有失败策略。实际请求仅要求所选分支有兼容当前协议的可用模型。预览和真实决策分开记录，统计按标签、来源、模型和Token分布，失败包含决策失败和后续模型调用失败。新决策保存规范化请求文本（最多16000字符）、来源、分类置信差及命中样本文本摘要/阈值快照；历史缺失字段不推测填充。日志和详情仅管理员可访问。分类置信差为最高类别与另一类别的相似度差，不能当成概率。

## 维护范围

开发临时传输包、测试脚本、隔离数据、构建/验收日志、过程截图和历史固定镜像发布工具已按用户要求清理。Git保留源码历史；正式源码、构建文件、固定审核模型、需求资料、数据库、Redis、品牌文件、密钥和业务日志属于维护保留项。正式发布备份保留于服务器/opt/AIGateway/backups，最近回退镜像保留。未入Git的历史开发、测试和发布脚本及开发登录记录因自动审批阻止暂未删除，等待用户确认。

运行、备份及恢复方法见deployment.md；接口说明见api.md；数据库结构见database-design.md与database-schema.sql。生产OpenAPI以正式应用/openapi.json为准。
