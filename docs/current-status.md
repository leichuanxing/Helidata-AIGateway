# 系统状态

当前应用版本：v0.1.1；数据库迁移版本：0022。生产主机192.168.31.97，源码目录/opt/AIGateway，正式入口18080，容器helidata-ai-gateway。当前镜像sha256:5b19fdce8cc4c00b968c2039ce124a25a28130c43ccafedc8c98de39cffeb928。

前端提供模型供应商、模型组、用户/用户组、模型广场、个人API Key、用量/调用日志、智能路由、内容合规、系统设置及备份运维。登录页采用居中卡片，支持现有明暗主题和角色跳转。全量产品复刻尚未完成，后续功能差距见product-reproduction.md；原始开发提示词、分阶段计划与Excel需求保留。

## 智谱供应商

| 类型 | 默认Base URL | 当前接入 |
| --- | --- | --- |
| 智谱开放平台 | https://open.bigmodel.cn/api/paas/v4 | OpenAI兼容Chat/SSE、嵌入、图像生成 |
| 智谱 Coding Plan | https://open.bigmodel.cn/api/coding/paas/v4 | OpenAI兼容Chat/SSE |

分别填写对应账户/套餐API Key及账户实际可用的模型名称。密钥加密保存，不返回明文。两个接入均未配置独立Responses端点，路由会过滤该操作。模型发现/连接检查执行GET /models，上游不提供此接口时手动配置映射；检查不会自动发起生成请求。Coding Plan使用范围与套餐规则见[官方说明](https://docs.bigmodel.cn/cn/coding-plan/quick-start)，开放平台见[官方API文档](https://docs.bigmodel.cn/cn/api/introduction)。

## 维护范围

开发临时传输包、测试脚本、隔离数据、构建/验收日志、过程截图和历史固定镜像发布工具已按用户要求清理。Git保留源码历史；正式源码、构建文件、固定审核模型、需求资料、数据库、Redis、品牌文件、密钥和业务日志属于维护保留项。正式发布备份保留于服务器/opt/AIGateway/backups，最近回退镜像保留。未入Git的历史开发、测试和发布脚本及开发登录记录因自动审批阻止暂未删除，等待用户确认。

运行、备份及恢复方法见deployment.md；接口说明见api.md；数据库结构见database-design.md与database-schema.sql。生产OpenAPI以正式应用/openapi.json为准。
