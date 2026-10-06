# 合力数据AI网关

HeliData AI Gateway提供模型供应商、模型权限、并发与配额、协议适配、智能路由、内容审核和运维管理。当前应用版本v0.1.2，数据库版本0026，正式入口为http://192.168.31.97:18080。当前功能与维护说明见[系统状态](docs/current-status.md)和[部署手册](docs/deployment.md)。

## 技术架构与目录

Vue3 / TypeScript / Element Plus / ECharts前端通过Nginx访问FastAPI。单容器内Supervisor管理Nginx、Uvicorn、PostgreSQL15、Redis；数据库安装pgvector0.8.7。HTTPX异步连接池承担真实上游请求，本地ONNX多语言模型承担审核向量化。持久数据统一挂载到`/data`，数据库和Redis端口不对外发布。

| 目录 | 内容 |
| --- | --- |
| frontend/ | 管理后台、个人门户、主题、图表和响应式页面 |
| backend/app/ | API、认证、网关流水线、Provider、后台作业 |
| backend/alembic/ | 0001至0022迁移 |
| config/ | config.yaml.example模板，无生产凭据 |
| docker/ | 完整Dockerfile、Nginx、Supervisor、entrypoint和模型下载脚本 |
| models/compliance/ | 固定版本权重、校验清单；下载脚本可重建 |
| docs/ | API、数据库、运维、当前功能说明及原始需求提取 |

## 系统要求、Docker构建与运行

Linux amd64及Docker Engine；建议至少4核CPU、8GiB内存、20GiB可用磁盘，另为数据库/日志/备份预留空间。建议不是性能承诺。首次构建需访问依赖源并下载约135MB模型。正式构建使用完整Dockerfile，不依赖历史阶段镜像：

```bash
cd /opt/AIGateway
python3 docker/fetch_compliance_model.py
docker build -f docker/Dockerfile -t helidata-ai-gateway:v0.1.2 .
mkdir -p /opt/AIGateway/data
docker run -d --name helidata-ai-gateway \
  -p 18080:80 -v /opt/AIGateway/data:/data:Z \
  --restart unless-stopped helidata-ai-gateway:v0.1.2
curl -fsS http://127.0.0.1:18080/health
```

当前服务器80端口由OpenResty使用，网关使用18080。SELinux保留`:Z`。生产访问建议使用可信HTTPS代理，来源和转发头配置一致后启用Secure Cookie。不要映射5432/6379。

## 初始化管理员与数据目录

首次初始化生成`admin`及随机密码，启动日志仅首次输出`INITIAL ADMIN`；管理员在受保护的终端查看、登录并改密。现有账号不会重置。禁止将初始化日志、生产配置、Master Key或备份打入公开源码包。

`/data/postgres`保存业务库及迁移，`redis`保存Redis数据，`config/config.yaml`保存基础设施配置，`config/provider-encryption.key`是Provider凭据解密必需的Master Key，`uploads`保存文件，`logs`包含运行日志及调用/审核持久补偿，`backup/manual`保存手动备份。恢复时必须保留数据库对应的Master Key。

## 设置与业务配置

超级管理员“系统设置”提供品牌PNG、系统URL、公开API Base URL、显示时区、容量/队列/超时/冷却、日志策略、共享向量、路由/合规总开关及Elasticsearch；既有登录安全参数保留。业务设置存入数据库并热更新，版本冲突409；数据库、JWT签名密钥、Master Key不通过此API修改。公开API地址用于门户示例，管理请求始终同源。语言目前为简体中文；显示时区可配置，配额周期和统计分桶仍按北京时间。

正文预览默认关闭。开启后每份最多16KiB，内置密码/认证/密钥脱敏和附加正则，仅管理员可读；任意自然语言敏感内容无法保证自动识别。调用/路由/审核日志默认保留366天，后台分批清理；用量汇总、管理审计长期保留。模型列表巡检默认关闭，开启只检查模型列表，不执行生成。

1. “模型供应商”新增Provider，选择协议、Base URL、API Key、代理和容量。凭据AES-GCM加密，保存后不返回明文。测试使用模型列表接口。
2. 配置模型映射，将对外逻辑模型指向真实上游模型，设置类型及能力。原生接口需要供应商实际支持，不能为不支持的供应商补出Embedding/Rerank。
3. 创建模型组，设置模型顺序、调度方式和Failover；对外返回逻辑模型名，内部保留路由轨迹。
4. 创建用户组，授予模型组权限，设置Token配额和组/Key并发；创建用户并关联组。
5. 用户在个人门户创建API Key，完整Key只显示一次，数据库保存摘要；之后可禁用/撤销。网页JWT与调用API Key用途不同。

## OpenAI与Streaming示例

替换模型为门户可见的逻辑模型，以环境变量或受保护的客户端配置存放Key：

```bash
export GATEWAY_BASE='http://192.168.31.97:18080/v1'
read -rs GATEWAY_API_KEY
export GATEWAY_API_KEY
curl -sS "$GATEWAY_BASE/models" -H "Authorization: Bearer $GATEWAY_API_KEY"
curl -sS "$GATEWAY_BASE/chat/completions" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"your-logical-model","messages":[{"role":"user","content":"你好"}],"max_tokens":32}'
curl -N "$GATEWAY_BASE/chat/completions" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"your-logical-model","messages":[{"role":"user","content":"你好"}],"stream":true,"max_tokens":32}'
```

OpenAI兼容SDK的`base_url`设为GATEWAY_BASE，使用网关API Key。Responses、Messages、Embeddings、Rerank和图片生成详见[API文档](docs/api.md)。SSE取消/超时释放资源；usage缺失标为未知，不伪造消费。流开始后错误不能改写已发送HTTP200，需检查终止事件和调用详情。

## 智能路由与内容审核

智能路由配置虚拟模型、实际Embedding逻辑模型、简单/复杂模型组、阈值及Top K；录入并向量化样本，以pgvector余弦检索决策。样本状态、版本和失败原因可追踪。该Embedding使用上游Provider，可能产生费用。

内容审核支持文本/通配/正则敏感词、本地语义样本、Audit/Block策略，按模型/组生效。Block先于生成和智能路由，不调用Provider生成；Audit保留证据并继续。本地语义模型与上游路由Embedding分别配置。审核证据保存ID、风险、版本、相似度快照，不保存原始客户正文。

## 备份恢复与升级

超级管理员“手动备份”创建任务，下载包含数据库custom dump、config、Master Key、uploads的包。包为0600且未加密，必须保存在受控存储；后台串行执行。维护窗口离线恢复，先在临时数据库验证，再恢复匹配配置、Master Key及文件。详见[运维手册](docs/deployment.md)。

升级先停入口流量、备份并记录旧镜像ID，停止/删除旧容器，再以相同/data和端口运行新镜像。启动自动执行Alembic head，检查健康、迁移、凭据和配置一致后恢复入口。不能只切回旧镜像就宣称数据库回滚完成。

## 故障排查与验收

`/health`检查就绪，`/health/detail`显示依赖状态，`docker exec helidata-ai-gateway supervisorctl status`查看四进程。401检查身份/Key状态，403检查角色/模型授权，429检查配额/并发/排队，502/504检查供应商协议/鉴权/网络/超时，503检查依赖与资源。用X-Request-ID关联详情和运行日志，不输出Key或完整配置。

数据库失联时调用日志写入0700目录中的0600补偿文件，恢复后幂等重放，不要删除补偿掩盖失败。设置冲突409需重新加载。需要回归时重新创建独立测试环境，不挂载生产数据或使用生产密钥。



智谱接入：模型供应商支持“智谱开放平台”和“智谱 Coding Plan”，选择类型自动填入对应Base URL。填写对应API Key和实际可用模型映射后保存；接入范围和模型发现限制见[系统状态](docs/current-status.md)。
