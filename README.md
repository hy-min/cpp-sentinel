# cpp-sentinel

[![CI](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml)

静态优先、LLM 去噪的 C++ 代码审查 Agent:
clang-tidy 扫出告警 → 结构化 → 符号层背景(谁调用谁) → 知识库检索 → LLM 逐条判定 → 报告。

**一句话卖点**:在自建 Juliet 规模化基准(3426 用例 → 451 条行级标注判定集,seed 可复现)上,
LLM 去噪把静态告警精度 0.47 → **0.89**(噪声过滤 92%)、召回 0.72,+RAG 后 F1 **0.825**;
小仓库消融(dkvstore)定位召回钥匙 = 跨文件使用侧证据;置信度校准实证 <0.8 二次判定门槛
(中置信桶准确率 0.00)。全部实验链见 `eval-report.md`。

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
python -m pytest tests/ -v          # 确定性单测(不打 LLM,数量以实际统计为准)
python eval/run_eval.py             # 三臂消融(A/B/C)重跑
python eval/recompute.py            # 版本对比汇总
```

## 设计注记(为什么这样做)

- LLM 只看告警文本会漏真缺陷(recall 0)→ 关键不是规则,是**跨文件使用侧证据**;
- clang-tidy/clang/libclang 版本在 22.1.8 与 18.1.1 之间存在差距(GitHub Actions 已如实暴露,
  均为 libclang 18.1.1 绑定,不影响 AST 遍历结果稳定性);
- RAG(5 条 CWE 小库)在真实仓库增益为 0,在 Juliet 合成库 +2.9pp F1 —— **增益场景依赖,如实报告**(P4)。
