# 系统设置入口迁移（2026-10-21）

将用户下拉菜单中的数据备份、管理审计入口迁入系统设置的独立标签，复用SystemOperations组件。旧/admin/backups和/admin/audit-logs跳转对应标签，支持直接链接和浏览器返回；保留配置草稿切换逻辑。按需加载组件，仅当前标签挂载并请求列表，离开备份页停止轮询。

权限保持不变：超级管理员拥有配置、系统状态、数据备份、管理审计；管理员仅显示管理审计，不请求系统配置接口；普通用户不能访问。后端super_administrator/administrator依赖未改动。普通管理员增加系统设置菜单以保留原有审计访问能力，不授予配置或备份权限。

备份创建、下载与审计筛选、详情功能复用，不修改数据库、恢复逻辑和生产数据。验证及部署信息待补充；部署前备份完整数据及数据库，保留旧容器，失败回滚，不推送GitHub。

验证：前端44项通过（新增4项角色导航与保存分流测试），vue-tsc和Vite生产构建通过；真实隔离HTTP权限专项1项通过，覆盖超级管理员、管理员、普通用户及匿名访问。本次没有后端业务代码改动，未重复执行完整后端套件。
部署：镜像sha256:9e0c7604b47c840b75b87dc9da3b88193b495a56cb302db8562b7f4ae8f7ead1；数据库0034、四个Supervisor进程RUNNING，Nginx配置检查成功。生产只读核验备份/审计/设置接口200及匿名401。备份/opt/AIGateway/backups/before-settings-operations-20261021T124752Z；回滚容器helidata-ai-gateway-before-settings-operations-20261021T124752Z。未新建或下载生产备份，未修改审计记录。

浏览器验收通过：两个旧地址分别跳转settings?tab=backups与settings?tab=audit；新标签切换正常，备份列表、审计筛选和记录正常，操作标签没有配置保存条，用户菜单只保留管理后台、用户中心、个人设置、退出。截图.deployment/settings-operations-deployed-20261021.png。隔离容器已停止。
