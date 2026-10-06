# 阶段 6：模型映射与模型组

2026-10-04，已完成本阶段开发、部署及验收。应用版本 0.6.0，Migration 0006，镜像 helidata-ai-gateway:stage6。访问地址 http://192.168.31.97:18080 。下一阶段为阶段 7 Gateway Core 基础链路。

## 实现范围

账号详情新增模型发现、手工映射、编辑、启停和软删除。一个逻辑名称可映射多个账号，一个账号可配置多个逻辑模型。同一账号同一逻辑名最多保留一条未删除映射；删除后允许重新创建。同名逻辑模型在各账号必须使用相同类型，冲突返回 409。支持文本、推理、多模态、Embedding、Rerank、Image 六种类型。

模型发现通过已有 Provider Adapter 发起实际 HTTP 请求：OpenAI 兼容协议访问配置 Base URL 下的 /models（通常为 /v1/models），Anthropic 使用原生列表及分页，Ollama 使用 /api/tags。发现结果去重，作为映射输入建议，不自动写入数据库。失败只返回脱敏错误和手工输入提示。禁用账号不能发现，但可预先配置手工映射。发现期间账号发生修改或禁用，旧结果返回 409。

Anthropic 分页沿用官方 [Models List](https://platform.claude.com/docs/en/api/http/models/list) 的 has_more、last_id 与 after_id；实现重复游标保护、页数/数量/耗时边界。接口返回模型列表不代表生成能力已验证。

模型组支持分页搜索、名称、描述、启停、逻辑模型多选、拖拽和上移/下移排序。完整成员顺序在一次事务中保存，position 从 0 开始，最多 100 个不同逻辑模型。该顺序供后续故障转移使用；本阶段没有执行生成或故障转移。已授权给用户组的模型组禁止删除，需先取消关联。

模型广场按当前用户组和模型组授权读取真实目录，JWT 与 API Key 目录共用权限逻辑。普通用户只看到授权组、逻辑名、类型、顺序和映射配置状态，不返回账号、Base URL、上游真实模型名或密钥。禁用用户组/模型组、撤销授权实时生效。可用候选过滤禁用/删除映射、禁用/删除账号、不健康和冷却中的账号，供阶段 7 Pipeline 复用。候选可用不等同真实上游生成验证；健康状态 unknown 不表示已测试。

## 数据结构

Migration 0006 新增 logical_models（稳定逻辑名与类型）、provider_model_mappings（账号到上游模型映射）和 model_group_models（组成员及顺序）。复用阶段 4 model_groups 和用户组授权表。组合外键约束逻辑名/类型一致，部分唯一索引约束未删除映射，组成员及位置有唯一约束。逻辑名在映射删除后保留，以保持组成员引用稳定；没有映射时目录显示不可用。现有用户、密码、账号密文和模型组字段保持。

## 接口

管理接口仅管理员/超级管理员可调用，均使用现有登录、CSRF、审计与标准错误机制。

| 接口 | 用途 |
| --- | --- |
| POST /api/admin/providers/{id}/discover-models | HTTP 模型发现 |
| GET /api/admin/logical-models | 逻辑名及类型选择列表 |
| GET /api/admin/providers/{id}/model-mappings | 账号映射列表 |
| POST /api/admin/providers/{id}/model-mappings | 新增映射 |
| PUT /api/admin/providers/{id}/model-mappings/{mapping_id} | 完整编辑映射 |
| DELETE /api/admin/providers/{id}/model-mappings/{mapping_id} | 软删除映射 |
| GET/POST /api/admin/model-groups | 列表与新增 |
| GET/PUT/DELETE /api/admin/model-groups/{id} | 详情、完整编辑、删除保护 |
| GET /api/portal/models | 当前登录用户的授权目录 |
| GET /api/gateway/models | 当前 API Key 所属用户的授权目录 |

/api/gateway/models 为内部授权目录接口；OpenAI 标准 /v1/models 与生成请求链路在后续阶段接入。

## 验收与部署

TypeScript/Vue/Vite 和 Docker 构建通过。tests/stage6_acceptance.py 使用实际 HTTP 协议夹具验证发现去重、Anthropic 分页、失败后手工映射、多对多映射、类型和归属约束、顺序保存、JWT/API Key 授权隔离、未授权隐藏、禁用/撤销授权过滤、软删除重建、引用删除保护及配置变更竞态。tests/stage6_migrations.py 在临时数据库验证 0001→0006 和降级再升级，比较旧用户密码、已有账号密文与模型组数据。tests/stage6_startup.py 验证严格 0700 新数据卷初始化、迁移与首次改密。第 5 阶段 Provider 验收全部回归通过，覆盖原生协议、代理、加密、失败脱敏与竞态。

浏览器验证模型组编辑与顺序按钮、账号映射列表和手工输入表单、普通用户模型广场、管理菜单隔离与退出。截图 stage6-model-groups.jpg、stage6-portal.jpg 仅包含已清理的临时验收数据；页面顺序调整取消，持久化由后端验收覆盖。临时账号处于禁用状态，目录如实显示无可用映射。

升级前备份 /data/backup/stage6-before-upgrade.sql。原用户/密码状态摘要比较一致；不重置管理员密码，不更换上游加密 Master Key。验收临时数据和隔离容器已清理，部署保持一个应用容器。完整验收记录见 stage6-validation.txt。

没有用户真实上游 Key，本阶段未进行付费账号鉴权成功或生成验收。实际 Pipeline、生成、Streaming、调度、故障转移、四级并发和配额执行按阶段 7–11 实现。本阶段完成后停止。
