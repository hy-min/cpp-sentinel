FROM condaforge/miniforge3:latest
WORKDIR /app

# 搬运式构建:cpp-review 环境已在本地打包好(conda pack),
# 避免构建机网络不稳定(IncompleteRead 断流已实测 6 次)。
COPY cppenv.tar.gz .
RUN mkdir -p /opt/conda/envs/cpp-review \
 && tar -xzf cppenv.tar.gz -C /opt/conda/envs/cpp-review

COPY . .

# 预热:让模型真正"干一次活"触发下载(构造不算!);代理仅构建时临时生效(--network host),
# 不写入镜像,运行容器不再需要网络
RUN HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890 \
    /opt/conda/envs/cpp-review/bin/python -c \
    "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2().embed_query('preheat')"

# 更新方式:把本地 cppenv.tar.gz 重新生成后 build 即可
CMD ["/opt/conda/envs/cpp-review/bin/python", "-m", "cpp_sentinel.cli"]
