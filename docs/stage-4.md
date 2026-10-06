# 阶段 4：用户组、API Key 与模型权限

本阶段以开发计划第九章和 Excel 的用户组/API Keys/用户管理联动为依据。仅完成阶段4范围，下一阶段为账号池与 Provider 管理。

## 实现

- Migration 0004 新增 api_keys、model_groups、user_group_model_groups。model_groups 为授权外键的基础表，模型组成员和管理接口在阶段6扩展；当前不填充演示模型。
- 用户组分页搜索、新建、完整编辑、删除、状态、描述、Token配额、daily/monthly/permanent周期、用户组并发、单Key并发、允许模型组。0 Token表示无额度；实际扣减及并发执行在阶段11实现。
- 用户新增/编辑选择真实用户组，列表/详情显示组名，归属变更立即撤销JWT会话。删除已被用户引用的组返回409，包含历史软删除用户的引用。
- 用户自己的Key分页、详情、创建、改名、启停、软删除。管理员也不能获取或修改别人的Key。高熵随机Key格式sk-hd-，数据库仅保存SHA-256哈希、展示前缀/后缀和业务元数据。
- 创建响应仅一次返回secret。列表、详情、刷新登录响应、审计日志均不包含完整Key及其哈希。前端仅在当前组件内存保留完整Key，关闭弹窗或离开页面清除；页面刷新不能恢复。
- 独立Bearer API Key认证，与后台JWT分离。每次查询真实Key、用户、用户组及有效模型组；无权限缓存。拒绝禁用/删除Key、禁用/删除用户、首次待改密用户、未分组和禁用组。
- 网关身份检查 /api/gateway/identity 返回当前Key ID、用户ID、实时组策略及允许模型组ID，并更新最后使用时间。后续真实模型请求复用同一认证服务及 require_model_group；当前没有聊天、Token消耗或上游模型调用。
- 用户组和Key操作写入审计，resource_type分别为user_group/api_key，不记录密钥。

## API

| 方法与路径 | 功能 |
| --- | --- |
| GET/POST /api/admin/user-groups | 分页搜索 / 新增 |
| GET/PUT/DELETE /api/admin/user-groups/{id} | 详情 / 完整编辑 / 删除 |
| GET /api/admin/user-group-options | 用户编辑的组选择器 |
| GET /api/admin/model-group-options | 真实模型组选择器 |
| GET/POST /api/portal/api-keys | 自己的Key列表 / 创建（secret只返回一次） |
| GET/PATCH/DELETE /api/portal/api-keys/{id} | 自己的Key详情 / 改名与启停 / 软删除 |
| GET /api/gateway/identity | Bearer API Key身份和权限检查 |

接口采用data/error包装、X-Request-ID，API响应no-store。Key客户端不需要后台会话Cookie。禁用或变更在管理操作提交后对新请求生效；不撤回已开始的请求。

## 文件

backend/app/models/user.py、alembic/versions/0004_keys.py、schemas/access.py、api/admin/groups.py、api/portal/keys.py、api/key_identity.py、services/key_auth.py、services/sessions.py、main.py、api/health.py；frontend/src/views/Groups.vue、Keys.vue、Users.vue、UserDetail.vue、App.vue、main.ts、Health.vue。

## 验收

tests/stage4_acceptance.py 在容器内通过Nginx发起真实HTTP，检查PostgreSQL哈希与审计；使用随机前缀的临时用户/组/模型组并按ID清理。tests/stage4_migrations.py 在随机临时数据库升级、降级、再升级，保留原用户字段。tests/stage4_startup.py 在隔离网络的新数据卷验证初始化和目录权限。业务库只执行upgrade。

部署前备份 /data/backup/stage4-before-upgrade.sql；沿用原/data和现有管理员密码。部署地址 http://192.168.31.97:18080，镜像 helidata-ai-gateway:stage4，数据库版本0004。

测试结果和界面验收在完成后记入 docs/current-status.md。

验收全部通过；详见 current-status.md 与 stage4-validation.txt。浏览器截图为已清理临时数据：stage4-groups.jpg、stage4-keys.jpg。阶段3登录/权限/用户CRUD完整回归通过，最终容器单独运行且健康；本阶段结束。
