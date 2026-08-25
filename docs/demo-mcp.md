# Demo: Claude Code 调用 cpp-sentinel（MCP 实测记录, 2026-08-25）

> 前置: 本项目 `.mcp.json` 已注册 stdio server; 从 `/home/hy/cpp-sentinel` 目录启动 Claude Code。
> 对话原文压缩保留关键行。

## 用户指令

> 用 cpp-sentinel 工具审查 /home/hy/mini-store

## Claude Code 执行摘要（原文节录）

```
Thought: called cpp-sentinel ...
MCP 调用返回了四态摘要(共 10 条告警: 真问题 0 / 疑似 2 / 忽略 8 / 失败 0),
但摘要不含明细。我再用 CLI 跑一次拿到完整的报告明细,看看那 2 条"疑似"是什么。
```

## 结果与复核发现

- 10 条 clang-tidy 告警 → 真问题 0 / 疑似 2 / 忽略 8 / 失败 0（~9.5s, 约 ¥0.007）
- 8 条忽略均为风格/微优化类（std::endl×5、main 中 exception-escape、未用局部变量等）

**2 条"疑似"复核**：

1. `include/mini/service.h:15` (bugprone-unchecked-optional-access, 0.60) —
   **实为真 BUG**。LLM 判定时以"缺少调用路径证据"降为疑似，但**使用侧就在 src/main.cc**:
   `Fetch("")` 失败路径上 `value.value()` 对空 optional → UB。注释里也标了
   "★ 失败路径仍调 Get(): 空 optional → UB"，属典型 P1 类缺陷。
   修复建议: 调用侧失败分支先 `HasValue()` 再取值。
2. `src/service.cc:13` (performance-inefficient-vector-operation, 0.60) — 可忽略
   （MakeRange 内 push_back 规模极小，性能影响可忽略）。

## 观察（该 agent 独立得出的结论）

> 这次结果恰好暴露了工具的边界: 真缺陷的定义在 service.h，触发路径在 main.cc —
> LLM **只看到单条上下文**，于是把真 BUG 降成了"疑似"（四态设计里本应能到"真问题"）。
> 如果后续想提升，可以尝试在判定时加入**使用侧证据**（对应 eval 实验里的 v5 方向）。

## 与本项目 eval 结论的互证

该 Agent 在无引导下独立指出的方向（use-side evidence），与 `eval/` 五轮实验链的结论一致：
v1-v4 缺使用侧事实 → 漏检；v5 接入跨文件使用侧证据 → recall 0 → 1.0。
**两个独立路径（30 条标注×5 版迭代  vs  agent 现场直觉）指向同一根因。**
