# v1.0.5 离线部署

适用于 Linux amd64（x86_64）。目标机器须预装 Docker Engine、Bash、coreutils、findutils、util-linux；建议至少 4 核、8 GB 内存及 20 GB 空闲磁盘。部署包不包含 Docker 安装器。

镜像包含应用、PostgreSQL/pgvector、Redis、Nginx 和本地模型资源，部署无需联网。配置外部模型供应商后，调用外部模型仍需要对应网络及 API Key。

```bash
tar -xzf helidata-ai-gateway-v1.0.5-linux-amd64-offline.tar.gz
cd helidata-ai-gateway-v1.0.5-linux-amd64
sudo ./deploy-offline.sh
```

按提示依次输入：

1. 宿主机数据目录，默认 `/opt/AIGateway/data`。
2. 管理员用户名，默认 `admin`。
3. 管理员密码，12 至 128 位，至少包含大小写字母、数字、符号中的三类。
4. 再次输入密码，两次必须一致。
5. 应用端口，默认 `18080`。

密码输入隐藏，只通过标准输入生成 Argon2 哈希，明文不写入 Docker 环境变量、部署配置或启动日志。首次初始化后删除临时哈希文件。启动成功后输出登录地址、管理员用户名及密码使用说明。多网卡环境请使用能访问服务器的实际 IP。

仅支持新的空数据目录；已有容器或非空目录会拒绝覆盖，不会重置既有管理员。容器名称默认 `helidata-ai-gateway`，可通过 `APP_CONTAINER_NAME` 环境变量指定其他名称。

```bash
sudo ./start-offline.sh
sudo ./stop-offline.sh
```

脚本从 `deployment.env` 读取首次选择的目录及端口，停止应用保留容器及数据。首次启动默认最多等待 300 秒，可设置 `APP_START_TIMEOUT` 调整。启动失败时保留数据与容器，修复原因后执行启动脚本重试。

安装脚本先校验 `SHA256SUMS`，加载镜像后核对 `image-id.txt`，启动时使用 `--pull=never`。`manifest.json` 记录版本、源代码提交、架构和镜像信息。对外提供的校验文件用于验证部署压缩包和独立镜像文件。
