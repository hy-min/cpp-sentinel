# cpp-sentinel

[![CI](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml)

静态优先、LLM 去噪的 C++ 代码审查 Agent:
clang-tidy 扫出告警 → 结构化 → 符号层背景(谁调用谁) → 知识库检索 → LLM 逐条判定 → 报告。

**一句话卖点**:在 1300 行 C++ 仓库(dkvstore)上,静态告警 30 条中仅 3.3% 是真问题;
接入符号层证据后,LLM 召回率 0 → 1.0(精度 1.0,误报 0)——详见 `eval/` 实验链。

## 环境(版本三处同版:本地/CI/Docker)

```bash
conda create -n cpp-review python=3.11 clang-tools=22.1.8 clang=22.1.8 clangxx=22.1.8 -c conda-forge -y
pip install -r requirements.txt
export DEEPSEEK_API_KEY=<你的key>
```

## 快速开始(一条命令端到端)

```bash
python -m cpp_sentinel.cli          # 默认扫 /home/hy/dkvstore,报告落在 out/
```

## 测试 & eval

```bash
python -m pytest tests/ -v          # 16 项确定性单测(不打 LLM)
python eval/run_eval.py             # 三臂消融(A/B/C)重跑
python eval/recompute.py            # 版本对比汇总
```

## 设计注记(为什么这样做)

- LLM 只看告警文本会漏真缺陷(recall 0)→ 关键不是规则,是**跨文件使用侧证据**;
- clang-tidy/clang/libclang 版本在 22.1.8 与 18.1.1 之间存在差距(GitHub Actions 已如实暴露,
  均为 libclang 18.1.1 绑定,不影响 AST 遍历结果稳定性);
- RAG(5 条 CWE 小库)增益为 0 —— **负结果如实报告**。
