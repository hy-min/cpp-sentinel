# Dogfood CI：把 cpp-sentinel 接进 gr-ieee802-11

目标：cpp-sentinel 的第一个真实用户 = 我们自己的旗舰仓库（986 commits 的 gr-ieee802-11）。
语义：**PR/push 增量审查**——只审变更文件、只报落在新代码上的告警（基线抑制），
LLM 判定后写进 job summary；默认建议模式（不挂 PR），`--gate` 可切门控模式。

## 一键接入（3 步）

1. 在 gr-ieee802-11 仓库 **Settings → Secrets and variables → Actions** 新建 `DEEPSEEK_API_KEY`。
2. 把下面的 YAML 存为 gr-ieee802-11 的 `.github/workflows/cpp-sentinel.yml`，推送。
3. 下一个含 C++ 变更的 PR/push 即触发；结果在该 workflow run 的 Summary 页。

```yaml
name: cpp-sentinel 增量审查
on:
  pull_request:
    paths: ["lib/**", "include/**"]
  push:
    branches: [main, TEST2]
    paths: ["lib/**", "include/**"]

permissions:
  contents: read

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }

      - uses: conda-incubator/setup-miniconda@v3
        with:
          activate-environment: cpp-review
          python-version: "3.11"

      - name: 装 clang-tools 与 GNU Radio(cmake configure 需要头文件)
        run: conda install -n cpp-review clang-tools=22.1.8 clang=22.1.8 clangxx=22.1.8 gnuradio uhd -c conda-forge -y

      - name: 装 gr-foo(gr-ieee802-11 上游依赖)
        run: |
          git clone --depth 1 https://github.com/bastibl/gr-foo /tmp/gr-foo
          cmake -S /tmp/gr-foo -B /tmp/gr-foo/build -DCMAKE_INSTALL_PREFIX="$CONDA_PREFIX"
          cmake --build /tmp/gr-foo/build -j"$(nproc)"
          cmake --install /tmp/gr-foo/build

      - name: 生成编译数据库(仅 configure,不构建)
        run: cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DCMAKE_PREFIX_PATH="$CONDA_PREFIX"

      - name: 取 cpp-sentinel
        run: git clone --depth 1 https://github.com/hy-min/cpp-sentinel /tmp/cpp-sentinel

      - name: 增量审查(建议模式;加 --gate 则高置信 real 挂 PR)
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          PYTHONPATH: /tmp/cpp-sentinel
        run: |
          pip install -r /tmp/cpp-sentinel/requirements.txt
          BASE="${{ github.event.pull_request.base.sha || github.event.before }}"
          DOTS=3; [ "${{ github.event_name }}" = "push" ] && DOTS=2
          python -m cpp_sentinel.ci --repo . --base "$BASE" --dots "$DOTS" --workers 8
```

## 设计要点（面试口径）

- **基线抑制**：`incremental.changed_lines()` 从 `git diff --unified=0` 解析新增行区间，
  `filter_to_changed()` 只保留落在新代码上的告警——存量技术债不淹没 PR 评审。
  已在真实仓库验证（gr-ieee802-11 `39ecea2..HEAD`：7 个变更文件，区间抽取正确）。
- **PR/push 双触发**：PR 用三点 diff（对 merge-base），push 用两点 diff（对推送前 SHA）；
  单人直推工作流也有审查覆盖。
- **编译数据库只要 configure**：`cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON` 不构建，
  CI 时间大头是 conda 依赖（gnuradio/uhd），可后续用缓存优化。
- **建议模式默认**：结果写 `GITHUB_STEP_SUMMARY`，不拦 PR；`--gate` 时
  real 且置信 ≥0.8 才退出码 1——与"置信度门槛"设计同源。

## 已知待验证项（如实）

- gr-ieee802-11 的 cmake configure 在纯净 CI 环境的完整依赖链（gnuradio/uhd/gr-foo 之外）
  未经实跑；首次触发若 configure 失败，按报错补缺即可，ci 驱动逻辑本身已本地验证。

---

## 本地端到端首跑验证（2026-08-27，上 CI 前）

在 gr-ieee802-11 真实 diff（`39ecea2..HEAD`，P174→P177 共 7 个变更文件）上完整跑通：

```
变更文件 7 → 静态告警 161 → 基线抑制后 4 条入审
→ 并发 8 路判定 97.3s → 真问题 0 / 疑似 3 / 忽略 1
（其中 3 条置信 <0.8 触发二次判定——置信度门槛在真实数据上首次生效）
💰 单次审查成本 ¥0.007
```

链路验证项全绿：变更行区间抽取 ✓ 基线抑制（161→4）✓ 使用侧索引构建 ✓
并发判定 ✓ 二次判定门槛 ✓ token 账单 ✓
