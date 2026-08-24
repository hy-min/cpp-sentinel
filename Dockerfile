FROM condaforge/miniforge3:latest
WORKDIR /app
COPY requirements.txt .

# 三件套同版(22.1.8)+ python deps —— 与本地/CI 完全一致
# 注意:容器内 Linux 网络(可能)无代理,conda/pip 走国内镜像
RUN conda create -n cpp-review python=3.11 clang-tools=22.1.8 clang=22.1.8 clangxx=22.1.8 \
      -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge -y \
 && /opt/conda/envs/cpp-review/bin/python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY . .

# 运行示例:
#   docker build -t cpp-sentinel .
#   docker run --rm cpp-sentinel python -m cpp_sentinel.cli
CMD ["/opt/conda/envs/cpp-review/bin/python", "-m", "cpp_sentinel.cli"]
