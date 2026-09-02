# cpp-sentinel

[![CI](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/hy-min/cpp-sentinel/actions/workflows/ci.yml)

静态优先、LLM 去噪的 C++ 代码审查 Agent:
clang-tidy 扫出告警 → 结构化 → 符号层背景(谁调用谁) → 知识库检索 → LLM 逐条判定 → 报告。

**一句话卖点**:在自建 Juliet 规模化基准(3426 用例 → 451 条行级标注判定集,seed 可复现)上,
LLM 去噪把静态告警精度 0.47 → **0.89**(噪声过滤 92%)、召回 0.72(行级真值;
**语义缺陷识别率 0.95**,三层口径修正链见 P4-3);**check 族路由**(数据流 check 走
agentic 工具调用、其余走单判)把 F1 推到 **0.853**、token 仅 1.45×(P11,消融链首个
CONFIRMED);小仓库消融(dkvstore)定位召回钥匙 = 跨文件使用侧证据;置信度校准实证 <0.8
二次判定门槛(中置信桶准确率 0.00)。全部实验链见 `eval-report.md`。

## 环境(版本三处同版:本地/CI/Docker)

```bash
conda create -n cpp-review python=3.11 clang-tools=22.1.8 clang=22.1.8 clangxx=22.1.8 -c conda-forge -y
pip install -r requirements.txt
export DEEPSEEK_API_KEY=<你的key>
```

## 快速开始(一条命令端到端)

```bash
python -m cpp_sentinel.cli          # 默认扫 /home/hy/dkvstore,报告落在 out/
uvicorn cpp_sentinel.api:app        # 服务化: POST /api/review;观测: GET /metrics(Prometheus 文本) /healthz
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
- RAG:真实仓库零增益(P4);P6 实测检索层准确率≈随机(跨语言嵌入失效);P7 双语语料把检准率修到 4 倍后下游 F1 依然零增益——**该任务知识注入边际≈0,瓶颈在判定证据不在检索**(P4/P6/P7 完整链条)。
- Agentic(P10):工具调用让 LLM 自主取证,召回 0.72→0.81 但精度 −3.5pp、token 5×——**精度-召回平移而非净收益,NOT CONFIRMED**;KB 在 LLM 自主检索下仍零增益(第四次复验)。
- check 族路由(P11):数据流 check(bugprone-unchecked-*/realloc)走 agentic、其余走单判——F1 **0.853**(超此前全部臂)、token 仅 1.45×,**CONFIRMED**;oracle 天花板 0.857,语义规则拿下 99.5%;KB 第五次零增益(路由 T-lite ≈ T 且更便宜)。

```bash
python eval/run_agentic.py --arm all    # P10 消融重跑(支持断点续跑)
python eval/route_p11.py                # P11 路由分析(零 LLM 成本,确定性复算)
```
