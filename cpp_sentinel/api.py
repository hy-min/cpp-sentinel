"""cpp_sentinel FastAPI 服务层:把审查管线暴露成 POST /api/review。

用法:
    uvicorn cpp_sentinel.api:app --reload
"""

import os
import time
from pathlib import Path

# ── R1 铁律:任何 LLM 库 import 之前清代理(与 cli.py 同款)──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from cpp_sentinel import observe
from cpp_sentinel.cli import run
from cpp_sentinel.report import make_report

app = FastAPI(title="cpp-sentinel",
              description="静态优先、LLM 去噪的 C++ 代码审查服务")


class ReviewRequest(BaseModel):              # ① 请求契约:客户端必须这么发
    repo: str = Field(description="要审查的 C++ 仓库路径")
    limit: int = Field(3, ge=1, le=100, description="最多判定几条告警")
    workers: int = Field(4, ge=1, le=16, description="并发窗口数")


@app.post("/api/review")                     # ② 声明:POST 这个 URL 会进下面的函数
def review(req: ReviewRequest):              # ③ 同步端点,FastAPI 自动放线程池跑
    if not os.environ.get("DEEPSEEK_API_KEY"):               # ④ 服务端配置检查
        raise HTTPException(status_code=503,
                            detail="服务端未配置 DEEPSEEK_API_KEY")
    db = Path(req.repo) / "build" / "compile_commands.json"  # ⑤ 入口校验:仓库可不可审
    if not db.exists():
        raise HTTPException(status_code=400,
                            detail=f"找不到编译数据库 {db} —— 先跑 cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON")
    t0 = time.perf_counter()
    results = run(req.repo, req.limit, req.workers)          # ⑥ 复用课6 的合龙(管线)
    observe.record_review(results, time.perf_counter() - t0)  # ⑦ 观测记账
    return make_report(results)                              # ⑧ 报告 dict → 自动 JSON


@app.get("/healthz")
def healthz():                                   # 存活探针(k8s/负载均衡用)
    return {"ok": True}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():                                   # Prometheus 抓取端点
    return observe.render()
