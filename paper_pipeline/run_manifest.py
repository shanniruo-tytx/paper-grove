#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_manifest.py — 执行记录 (Run Manifest) + Resume 支持

每次 pipeline 执行产生一份 machine-readable run record，记录每个 stage 状态：
  PENDING / RUNNING / PASS / FAIL / SKIPPED / REUSED

Resume 机制：stage 输出可缓存（resolved metadata / source manifest / canonical），
重跑时若上游 stage 已 PASS 且缓存存在，则标记 REUSED 而非重新执行（省网络/省 token/避免漂移）。
"""
from __future__ import annotations
import json, os, datetime as _dt
from typing import Dict, List, Optional

STAGE_PENDING = "PENDING"
STAGE_RUNNING = "RUNNING"
STAGE_PASS = "PASS"
STAGE_FAIL = "FAIL"
STAGE_SKIPPED = "SKIPPED"
STAGE_REUSED = "REUSED"

# pipeline 标准 stage 顺序
STAGES = ["locator", "reader", "canonical", "deep_renderer", "plain_renderer",
          "semantic_gate", "importer", "build"]


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class RunManifest:
    def __init__(self, run_id: str, paper_id: str, input_url: str, pipeline_version: str):
        self.run_id = run_id
        self.paper_id = paper_id
        self.input = input_url
        self.started_at = _now()
        self.finished_at: Optional[str] = None
        self.pipeline_version = pipeline_version
        self.stages: Dict[str, dict] = {s: {"status": STAGE_PENDING, "detail": ""} for s in STAGES}
        self.outputs: Dict[str, str] = {}
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def set_stage(self, name: str, status: str, detail: str = ""):
        if name not in self.stages:
            self.stages[name] = {}
        self.stages[name] = {"status": status, "detail": detail, "at": _now()}

    def mark_reused(self, name: str, detail: str = "缓存命中，跳过重算"):
        self.stages[name] = {"status": STAGE_REUSED, "detail": detail, "at": _now()}

    def add_output(self, key: str, path: str):
        self.outputs[key] = path

    def add_error(self, msg: str):
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def finish(self):
        self.finished_at = _now()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "paper_id": self.paper_id,
            "input": self.input,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pipeline_version": self.pipeline_version,
            "stages": self.stages,
            "outputs": self.outputs,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "RunManifest":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        obj = cls.__new__(cls)
        for k, v in d.items():
            setattr(obj, k, v)
        return obj


def make_run_id(paper_id: str) -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    short = abs(hash(paper_id)) % 100000
    return f"run_{ts}_{short}"


if __name__ == "__main__":
    rm = RunManifest("run_x", "doi:10.1/x", "https://mp.weixin.qq.com/s/abc", "paper-pipeline-v3")
    rm.set_stage("locator", STAGE_PASS)
    rm.mark_reused("canonical", "缓存命中")
    rm.add_output("canonical", "/tmp/c.json")
    rm.finish()
    print(json.dumps(rm.to_dict(), ensure_ascii=False, indent=2))
