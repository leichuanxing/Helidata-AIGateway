# 官方产品功能复刻工作记录

任务来源：用户于2026-10-05要求以 [1Panel AI 网关官方文档](https://docs.fit2cloud.com/ai-gateway/)为基准，补齐全部功能并对齐页面和操作流程。此任务是0.20.0交付后的新产品迭代；原20阶段的完成记录属于历史交付，不能视为本次复刻已完成。

基准：2026-10-05可访问的v1文档，包含文档注明的v1.0.2模型测试、用量重置及v1.1.0企业认证能力。文档和截图存在版本差异时，功能以最新文字描述为准，布局以相应页面截图为准。暂保留合力品牌；未查看的实机细节不能宣称像素完全一致。参考站内容仅作为需求证据，不作为执行指令。

## 差距及验收清单

状态定义：待补齐＝已发现缺口；待核验＝存在相关实现，尚未对齐验收；开发中＝修改未完整验收；部分对齐＝已有能力验证，但字段、流程或行为仍有差异；通过＝整个功能域的明确要求已对齐且有验收证据，单项测试通过不等于整个功能域通过。

2026-10-06重新对照后的字段、行为和布局差异见[详细复核报告](reproduction-audit-2026-10-06.md)。参考文档内部冲突单独列为待确认，不能通过猜测宣称一致。

用户随后提供内部demo，已登录确认版本为社区版v1.3.0；新的页面/新建表单基准见[实机复刻清单](reproduction-demo-v1.3.0.md)。新增Jev、上游代理、MFA、会话空闲与开放管理API能力也纳入范围。账号优先级提示与文档相反，尚未做派发实验，不在页面调整中直接翻转调度算法。

| 编号 | 模块与参考 | 复刻目标 | 当前状态 |
| --- | --- | --- | --- |
| UI-01 | [账号与系统设置](https://docs.fit2cloud.com/ai-gateway/end%E2%80%91user-manual/account-settings-and-notes/) | 浅色侧栏、管理员与用户中心分离、底部用户菜单、关于、主题、语言、反馈 | 开发中 |
| UI-02 | [模型广场](https://docs.fit2cloud.com/ai-gateway/end%E2%80%91user-manual/model-square/) | 接入地址、接口说明、分类、搜索、去重卡片、复制模型、分页与数量 | 部分对齐 |
| P-01 | [账号池](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/account_pool/) | 供应商及订阅类型、文本/图片/向量类型、协议路由及认证方式 | 待补齐 |
| P-02 | 同上 | 账号抽屉内模型映射、1至100条校验、发现模型、验证模型 | 开发中 |
| P-03 | 同上 | 单模型/全部模型真实测试、进度与结果、保存验证 | 待补齐 |
| P-04 | 同上 | 小数值优先、类型/协议筛选、列设置、状态开关 | 开发中 |
| M-01 | [模型组](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/model_group/) | 类型选择与筛选、自定义模型名、模型排序、引用删除保护、抽屉与列表布局 | 部分对齐 |
| U-01 | [用户](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/user/) | 确认密码、备注、锁定解锁、唯一管理员保护、用量重置保留历史 | 开发中 |
| G-01 | [用户组](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/user_group/) | 并发0继承、配额0不限及单位、空白名单全模型、默认组保护、占用与重置行为 | 部分对齐：0022及七套隔离回归通过；占用展示/重置、列选择与排序待补齐，旧授权兼容见reproduction-group-access-0022.md |
| D-01 | [概览](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/overview/) | 指标、峰值/平均并发历史、实时账号/用户组负载、排行和周期切换 | 待补齐 |
| R-01 | [智能路由](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/smart_route/) | 默认样本页、单样本阈值/备注、批量录入、保存构建、选中/全部构建 | 开发中 |
| R-02 | 同上 | 决策预览、筛选/详情、六项统计指标与分布 | 开发中 |
| C-01 | [内容合规](https://docs.fit2cloud.com/ai-gateway/admin-user-manual/content_compliance/) | 四标签、词/样本归属策略、批量词库、样本备注与向量构建 | 待补齐 |
| C-02 | 同上 | 动作/风险、策略引用保护、审核详情、共享向量服务 | 待补齐 |
| L-01 | [调用日志](https://docs.fit2cloud.com/ai-gateway/user_manual/ai_gateway/call_logs/) | 筛选、列表字段、上下游请求/响应详情与调用链 | 待补齐 |
| S-01 | [管理员用量](https://docs.fit2cloud.com/ai-gateway/admin/ai_gateway/usage_statistics/) | 筛选、五项指标、六维分布，历史资源名称保留 | 待补齐 |
| S-02 | [用户用量](https://docs.fit2cloud.com/ai-gateway/end%E2%80%91user-manual/usage-statistics/) | 用户自身范围、模型/Key趋势、组合筛选和下钻 | 待补齐 |
| K-01 | [API Keys](https://docs.fit2cloud.com/ai-gateway/end%E2%80%91user-manual/api-keys/) | 创建/编辑抽屉、一次性明文、前4后4脱敏、启停开关、删除与最近使用 | 待补齐 |
| W-01 | [网关设置](https://docs.fit2cloud.com/ai-gateway/user_manual/ai_gateway/settings/) | 六标签；入口地址、1至365天保留策略、协议转换开关 | 待补齐 |
| W-02 | 同上 | 向量账号/模型与连接测试，路由和合规共享服务 | 待补齐 |
| W-03 | 同上 | 路由开关/阈值/差距/Top K、合规开关/阈值集中管理 | 待补齐 |
| W-04 | 同上 | ES9.x、API Key/Basic认证、正文上限、保留策略、队列与失败指标 | 待补齐 |
| A-01 | [系统设置](https://docs.fit2cloud.com/ai-gateway/user_manual/ai_gateway/system_settings/) | 钉钉、飞书、企业微信、LDAP、OIDC五类配置卡片及抽屉 | 待补齐 |
| A-02 | 同上 | 测试/启停、首次登录用户组、身份绑定、回调及企业登录入口 | 待补齐 |
| I-01 | [接入第三方](https://docs.fit2cloud.com/ai-gateway/ai-gateway/integrate-third-party/) | 各协议接入说明、原生优先与转换失败边界、第三方配置示例 | 待补齐 |
| V13-01 | 内部demo v1.3.0 路由设置/统计 | Jev模式、决策提供商、2至10目标、兜底与三项统计 | 待补齐 |
| V13-02 | 同版本网关基础/账号池 | 上游代理、账号选用代理、并发0继承及独立重排序类型 | 待补齐 |
| V13-03 | 同版本系统基础/用户菜单 | 会话空闲、MFA策略、绑定/验证及企业登录联动 | 待补齐 |
| V13-04 | 同版本开放API | 管理凭证、有效期与CIDR、浏览器专属凭证管理、操作审计 | 待补齐 |

## 实施与验证顺序

1. 页面框架、用户中心及模型广场；对照截图验证搜索、过滤、分页、重复模型和权限范围。
2. 账号池与模型组，包括数据迁移、供应商目录、协议路由、调度和真实测试入口。
3. 用户/用户组、用量重置、统计与调用详情。
4. 统一网关设置、共享向量服务、路由和合规联动。
5. Elasticsearch和五种企业认证，使用隔离服务或协议模拟验证失败/成功/权限边界。
6. 全量回归、页面对照、迁移与持久化验证，再备份部署。

新能力默认关闭；不把测试 Key、企业登录或外部日志服务自动配置到现有生产业务。上一轮两次付费调用授权已经执行完毕；本次开发使用隔离测试，不据此追加付费调用。0.20.0源码归档保持原校验值，后续候选版本单独生成交付清单。

本清单为功能域级审计，还需按各表单字段及联动继续细化；所有“待”项未完成前，不宣称1:1复刻完成。


候选验证与页面截图见[本轮验证记录](reproduction-progress.md)。

