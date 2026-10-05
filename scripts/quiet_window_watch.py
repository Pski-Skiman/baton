#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bounded sampled quiet-window observer; not a termination permission."""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import attribution          # 变化归属判定（与 shutdown_plan 共用，口径必须一致）
except ImportError as e:
    sys.stderr.write("FATAL: attribution.py 不可用（%s）；拒绝降级运行\n" % e)
    sys.exit(9)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_IGNORE = {"proj"}
# 匹配到行尾：[^\n]* —— v2 只匹配到 "**豆包**" 就停，导致哈希恒定
DEFAULT_PARTY_LINE = r"^\|\s*\*\*{party}\*\*[^\n]*"
_last_log = None


def log(event, **kw):
    global _last_log
    signature = json.dumps([event, kw], ensure_ascii=True, sort_keys=True)
    if signature == _last_log:
        return
    _last_log = signature
    kw["event"] = event
    kw["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def read_once(path):
    """一次读取，返回 (ok, text, err)。哈希与扫描必须用同一次读到的字节。"""
    try:
        if not os.path.exists(path):
            return False, "", "missing"
        with open(path, "rb") as f:
            raw = f.read()
        try:
            return True, raw.decode("utf-8"), ""
        except UnicodeDecodeError:
            return False, "", "decode-error"
    except PermissionError:
        return False, "", "permission-denied"
    except OSError as e:
        return False, "", "os-error:%s" % e.__class__.__name__


def norm_line(s):
    """署名行归一化：去行尾空白与尾部孤立竖线（不以尾随空格判定"变化"）。"""
    s = s.rstrip()
    while s.endswith("|"):
        s = s[:-1].rstrip()
    return s


def party_signature(text, party, tmpl):
    """抓取该方在签到表里的整行并哈希。"""
    pat = re.compile(tmpl.format(party=re.escape(party)), re.M)
    hits = [norm_line(m.group(0)) for m in pat.finditer(text)]
    if not hits:
        return None
    return attribution.sha16("||".join(hits))


def main():
    global _last_log
    _last_log = None
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--me", required=True, help="本方 id 前缀（wb / dsh / codex / doubao / copilot）")
    ap.add_argument("--files", action="append", default=[], help="共享载体（可重复；不给则扫目录所有 .md）")
    ap.add_argument("--party", action="append", default=[], help="他方名，用于署名区探测（可重复）")
    ap.add_argument("--party-line", default=DEFAULT_PARTY_LINE, help="署名行正则模板，{party} 为占位")
    ap.add_argument("--window", type=int, default=300)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--max-minutes", type=int, default=30)
    ap.add_argument("--ignore-prefix", action="append", default=[])
    a = ap.parse_args()

    if a.window <= 0 or a.interval <= 0 or a.max_minutes <= 0:
        log("ERROR", reason="window-interval-and-max-minutes-must-be-positive")
        return 1
    if not re.fullmatch(r"[a-zA-Z0-9_]+", a.me):
        log("ERROR", reason="invalid-message-prefix")
        return 1

    root = a.dir
    if not os.path.isdir(root):
        log("ERROR", reason="dir-not-found", dir=root)
        return 1

    paths = [os.path.join(root, f) for f in a.files] if a.files else \
            [os.path.join(root, f) for f in os.listdir(root) if f.lower().endswith(".md")]
    if not paths:
        log("ERROR", reason="empty-watch-set")
        return 1
    root_abs = os.path.realpath(root)
    try:
        if any(os.path.commonpath([root_abs, os.path.realpath(p)]) != root_abs for p in paths):
            log("ERROR", reason="watch-path-outside-shared-root")
            return 1
        for q in a.party:
            re.compile(a.party_line.format(party=re.escape(q)), re.M)
    except (ValueError, KeyError, IndexError, re.error):
        log("ERROR", reason="invalid-path-or-party-template")
        return 1

    me = a.me.lower()
    ignore = set(x.lower() for x in a.ignore_prefix) | DEFAULT_IGNORE
    parties = a.party

    # 基线：按文件存归属快照（preamble 哈希 + 每块哈希）+ 各方署名行哈希
    base = {}
    for p in paths:
        ok, text, err = read_once(p)
        base[p] = {"ok": ok, "err": err,
                   "snap": attribution.snapshot(text) if ok else None,
                   "sigs": {q: party_signature(text, q, a.party_line) for q in parties} if ok else {}}

    unreadable0 = [{"file": os.path.basename(p), "error": base[p]["err"]}
                   for p in paths if not base[p]["ok"]]
    if unreadable0:
        log("ERROR", reason="baseline-unreadable", files=unreadable0,
            note="基线就有文件读不到 ⇒ 拒绝运行（无证据不得判窗口）")
        return 1

    missing_sig = [q for q in parties if any(base[p]["sigs"].get(q) is None for p in paths)]
    last_other = time.monotonic()
    log("START", version="0.2", me=me, window_sec=a.window, interval_sec=a.interval,
        max_minutes=a.max_minutes, files=len(paths), parties=parties,
        baseline_ids=sum(len(base[p]["snap"]["ids"]) for p in paths),
        warn=("署名行未匹配到：" + ",".join(missing_sig)) if missing_sig else None)

    deadline = time.monotonic() + a.max_minutes * 60
    try:
        while True:
            time.sleep(max(0, min(a.interval, deadline - time.monotonic())))
            now = time.monotonic()

            unreadable, sig_changed, other_hits, mine_hits, unknown = [], [], [], [], []

            for p in paths:
                b = base[p]
                ok, text, err = read_once(p)
                if not ok:
                    unreadable.append({"file": os.path.basename(p), "error": err})
                    continue          # 读不到 ⇒ 不更新基线（回来时按旧基线比对 ⇒ 保守）
                for q in parties:
                    old = b["sigs"].get(q)
                    new = party_signature(text, q, a.party_line)
                    if old is not None and new is not None and old != new:
                        sig_changed.append({"party": q, "file": os.path.basename(p)})
                v = attribution.compare(b["snap"], text, me, ignore)
                if v["verdict"] == "other":
                    other_hits.append({"file": os.path.basename(p), "new": v["other_new"][:5],
                                       "changed": v["changed_other"][:5]})
                elif v["verdict"] == "unknown":
                    unknown.append({"file": os.path.basename(p), "why": v["why"],
                                    "detail": {"preamble_changed": v["preamble_changed"],
                                               "removed": v["removed"][:5],
                                               "changed_any_existing": v["changed_any_existing"][:5]}})
                elif v["verdict"] == "mine":
                    mine_hits.append({"file": os.path.basename(p), "new": v["mine_new"][:5]})
                # 基线滚动更新
                b["snap"] = attribution.snapshot(text)
                b["sigs"] = {q: party_signature(text, q, a.party_line) for q in parties}

            if unreadable:
                last_other = now
                log("UNREADABLE", files=unreadable,
                    note="必需载体读不到 ⇒ 无证据 ⇒ 保守重置窗口，且本次不输出 WINDOW_SATISFIED")
            elif sig_changed or other_hits:
                last_other = now
                log("HEARD_FROM_OTHERS", signature_changed=sig_changed, new_other=other_hits)
            elif unknown:
                last_other = now
                log("UNATTRIBUTED", files=unknown[:10],
                    note="差分无法全部归属本方 ⇒ 保守重置窗口；不输出 WINDOW_SATISFIED（宁长勿假）")
            else:
                quiet = now - last_other
                if mine_hits:
                    log("MINE_ATTRIBUTED", files=mine_hits,
                        note="全部差分可归属本方（仅新增本方消息块，其余零改动），不重置窗口")
                if quiet >= a.window:
                    log("WINDOW_SATISFIED", quiet_sec=int(quiet),
                        note="仍须过 FIN 前置检查才可收尾；本结果不替代该检查",
                        caveat="严格归属、整行署名比较；读不到不给结论；仅覆盖所列文件采样")
                    return 0

            if now >= deadline:
                log("TIMEOUT", max_minutes=a.max_minutes,
                    note="记录真实阻塞和恢复条件；计时不替代用户等待指令或结束前检查")
                return 2
    except KeyboardInterrupt:
        log("INTERRUPTED")
        return 3


if __name__ == "__main__":
    sys.exit(main())
