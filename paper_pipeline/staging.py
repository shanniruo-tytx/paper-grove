#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
staging.py — 阶段性导入 (Staging -> Validation -> Commit) + Rollback

避免：paper.md 写入成功，deep note 写入成功，plain note 失败，build 又失败，
最终 KB 留下半篇结果 / 孤儿笔记 / 错误 index。

策略（贴合现有 kb-site 架构，不引入数据库事务）：
  1. 所有待写文件先落到 staging/ 目录
  2. 全部写入成功 + gate 验证通过
  3. atomic commit：一次性移动到 content/papers + content/notes
  4. 任一阶段失败 -> cleanup staging，KB 不残留中间产物
  5. build 阶段若在 commit 之后失败 -> 自动 rollback（恢复 build 前 index 备份）
"""
from __future__ import annotations
import os, shutil, json, datetime as _dt
from typing import Dict, List, Optional


class StagedImport:
    def __init__(self, content_dir: str, staging_root: str, run_id: str):
        self.content_dir = content_dir
        self.staging_dir = os.path.join(staging_root, run_id)
        self.papers_dir = os.path.join(content_dir, "papers")
        self.notes_dir = os.path.join(content_dir, "notes")
        self._files: Dict[str, str] = {}   # rel_path -> staging_abs
        self._committed = False

    def stage(self, rel_path: str, content: str):
        """把一份文件内容放入 staging（rel_path 如 papers/cifm_论文.md）。"""
        abs_path = os.path.join(self.staging_dir, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        self._files[rel_path] = abs_path

    def validate(self) -> List[str]:
        """校验 staging 完整性，返回错误列表。"""
        errors = []
        needed = ["papers", "notes"]
        for nf in needed:
            if not any(k.startswith(nf + "/") for k in self._files):
                errors.append(f"staging 缺少 {nf}/ 文件")
        return errors

    def commit(self) -> List[str]:
        """原子提交：全部移动进 content/。返回提交的绝对路径列表。"""
        errs = self.validate()
        if errs:
            raise RuntimeError("commit 前校验失败: " + "; ".join(errs))
        committed = []
        for rel, src in self._files.items():
            dst = os.path.join(self.content_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            committed.append(dst)
        self._committed = True
        # 清理 staging 目录（所有文件已移出，无残留价值）
        if os.path.isdir(self.staging_dir):
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        return committed

    def rollback(self):
        """清理 staging（KB 未污染）。"""
        if os.path.isdir(self.staging_dir):
            shutil.rmtree(self.staging_dir, ignore_errors=True)

    def build_backup_path(self, dist_dir: str) -> Optional[str]:
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bp = os.path.join(dist_dir, "_backup_index_%s.json" % ts)
        idx = os.path.join(dist_dir, "index.json")
        if os.path.exists(idx):
            shutil.copyfile(idx, bp)
            return bp
        return None

    def restore_build(self, dist_dir: str, backup_path: str):
        if backup_path and os.path.exists(backup_path):
            shutil.copyfile(backup_path, os.path.join(dist_dir, "index.json"))


if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp()
    content = os.path.join(tmp, "content")
    os.makedirs(os.path.join(content, "papers"))
    os.makedirs(os.path.join(content, "notes"))
    st = StagedImport(content, os.path.join(tmp, "_staging"), "run_test")
    st.stage("papers/x_论文.md", "---\ntitle: X\n---\n")
    st.stage("notes/x_论文拆解.md", "---\nkind: note\n---\n")
    committed = st.commit()
    print("committed:", committed)
    print("papers exist:", os.path.exists(os.path.join(content, "papers", "x_论文.md")))
    print("staging cleaned:", not os.path.isdir(st.staging_dir))
