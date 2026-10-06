# 本地审核模型来源

使用[Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small)的ONNX量化导出，固定revision `761b726dd34fb83930e26aab4e9ac3899aa1fa78`；原始模型为[intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)，发布方标注MIT许可。模型用途为本地内容审核语义向量，不替代智能路由的上游Embedding配置。

model.onnx和tokenizer.json的SHA256见manifest.json。完整Dockerfile在构建时再次校验；`docker/fetch_compliance_model.py`只下载固定版本并核对哈希后原子安装。镜像运行时不下载模型。交付包可包含已校验权重，也可通过脚本重建；初次Docker依赖安装仍需网络。
