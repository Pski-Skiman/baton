#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manual cancellable plan; checks facts and never performs system shutdown."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import attribution          # 变化归属判定（与 quiet_window_watch 共用，口径必须一致）
except ImportError as e:        # 缺失 ⇒ 拒绝运行，不得退回"看 id 前缀"的弱判定
    sys.stderr.write("FATAL: attribution.py 不可用（%s）；拒绝降级运行\n" % e)
    sys.exit(9)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MAX_RENEW = 2
MIN_MINUTES = 1          # 一般提醒的下限
INTERRUPT_MIN = 5        # 未完成时主动让出的项目等待下限
LOCK_TTL = 60            # 秒；超过视为陈旧锁
ID_RE = re.compile(r"\[id=([A-Za-z0-9_\-]+)\]")
DEFAULT_IGNORE = {"proj"}
WEAK_REASONS = {"再等等", "再等待", "等等", "再等", "继续等", "稍等", "等一下", ""}


def state_dir(d):
    sd = os.path.join(d, ".baton-state")
    os.makedirs(sd, exist_ok=True)
    return sd


def plan_path(d, who):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", who):
        raise ValueError("who must contain ASCII letters, digits, underscores or hyphens")
    return os.path.join(state_dir(d), "plan_%s.json" % who.lower())


def lock_path(d, who):
    return plan_path(d, who) + ".lock"


class PlanLock:
    """读-比较-写整段互斥；版本校验不是锁，不得抢占他方锁。

    规则：
      - 锁体带**一次性 token**，``release`` 只删自己那把（token 不匹配 ⇒ 拒绝并留痕）；
      - 锁龄超限或解析失败 ⇒ 只报 STALE_LOCK_SUSPECT，绝不删除。
    """

    def __init__(self, d, who):
        self.p = lock_path(d, who)
        self.held = False
        self.token = None
        self.note = None

    def acquire(self, tries=3, wait=1.0):
        for _ in range(tries):
            try:
                fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self.token = uuid.uuid4().hex
                try:
                    os.write(fd, json.dumps(
                        {"at": time.time(), "pid": os.getpid(), "token": self.token}).encode())
                finally:
                    os.close(fd)
                self.held = True
                return True, None
            except FileExistsError:
                info, err = None, ""
                try:
                    with open(self.p, "r", encoding="utf-8") as f:
                        info = json.load(f)
                except Exception as e:
                    err = e.__class__.__name__
                if not isinstance(info, dict) or not isinstance(info.get("at"), (int, float)):
                    # 解析失败 ⇒ 只怀疑，不删
                    self.note = {"kind": "STALE_LOCK_SUSPECT", "reason": "lock-unparsable:%s" % err,
                                 "path": self.p,
                                 "action": "人工确认持有者进程已死后手动删除并留痕；本进程未写入"}
                    return False, "STALE_LOCK_SUSPECT"
                age = time.time() - float(info.get("at", 0))
                if age > LOCK_TTL:
                    self.note = {"kind": "STALE_LOCK_SUSPECT", "age_sec": int(age),
                                 "holder_pid": info.get("pid"), "path": self.p,
                                 "action": "锁龄超过 TTL(60s)，但**活跃/暂停的持有者不等于已死**；"
                                           "不删除、不接管；人工确认后手动清理并留痕"}
                    return False, "STALE_LOCK_SUSPECT"
                time.sleep(wait)
        return False, "LOCK_BUSY"

    def release(self):
        if not self.held:
            return
        try:
            with open(self.p, "r", encoding="utf-8") as f:
                info = json.load(f)
        except FileNotFoundError:
            self.held = False
            return
        except Exception:
            info = None
        if isinstance(info, dict) and info.get("token") == self.token:
            try:
                os.remove(self.p)
            except OSError:
                pass
        else:
            # 锁已被他方持有，绝不删除。
            out({"event": "REFUSED_RELEASE_FOREIGN_LOCK", "path": self.p,
                 "note": "锁 token 与本人不匹配 ⇒ 未删除；避免 A.release 删掉 B 的锁"})
        self.held = False


def load(p):
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                st = json.load(f)
            if not isinstance(st, dict):
                return None
            if not isinstance(st.get("history", []), list) or not isinstance(st.get("_ver", 0), int):
                return None
            if st.get("status") == "armed":
                if (not isinstance(st.get("watch_files"), list) or
                    not all(isinstance(x, str) for x in st["watch_files"]) or
                    not isinstance(st.get("snapshots"), dict) or
                    not all(isinstance(v, dict) and isinstance(v.get("blocks"), dict)
                            for v in st["snapshots"].values()) or
                    not isinstance(st.get("renewals", 0), int)):
                    return None
            return st
        except Exception:
            return None          # 解码失败 ⇒ 明确区分，不当成"空计划"
    return {}


def save(p, st):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def nowstr():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def norm_rel(root, p):
    try:
        return os.path.relpath(os.path.abspath(p), os.path.abspath(root)).replace("\\", "/")
    except Exception:
        return p


def read_once(path):
    """一次读取，返回 (ok, text, err)；哈希与扫描必须用同一次读到的字节。"""
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


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def prefix_of(i):
    return i.split("-")[0].lower()


def scan_activity(st, root, me, ignore):
    """返回 (other_hits, mine_hits, unknown, problems)。

    归属判定统一走 attribution.py，与 quiet_window_watch 同口径：
      - ``mine``   = 全部差分可归属本方（**仅新增本方消息块**，其余无任何改动）⇒ 不阻塞；
      - ``other``  = 他方新增块／他方块被改 ⇒ 阻塞；
      - ``unknown``= preamble 变／块被删／既有块被改／占位块 ⇒ **保守阻塞**（宁长勿假）；
      - 读不到／无基线 ⇒ ``problems``，阻塞（不得给"未发现活动"）。
    """
    files = st.get("watch_files") or []
    snaps = st.get("snapshots") or {}
    problems, other_hits, mine_hits, unknown = [], [], [], []
    for rel in files:
        fp = os.path.join(root, rel)
        ok, text, err = read_once(fp)
        if not ok:
            problems.append({"file": rel, "error": err})
            continue
        snap = snaps.get(rel)
        if snap is None:
            problems.append({"file": rel, "error": "no-baseline-snapshot"})
            continue
        v = attribution.compare(snap, text, me, ignore)
        if v["verdict"] == "other":
            other_hits.append({"file": rel, "new": v["other_new"][:5],
                               "changed": v["changed_other"][:5]})
        elif v["verdict"] == "mine":
            mine_hits.append({"file": rel, "new": v["mine_new"][:5]})
        elif v["verdict"] == "unknown":
            unknown.append({"file": rel, "why": v["why"],
                            "detail": {"preamble_changed": v["preamble_changed"],
                                       "removed": v["removed"][:5],
                                       "changed_any_existing": v["changed_any_existing"][:5]}})
    return other_hits, mine_hits, unknown, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["arm", "cancel", "renew", "status", "check"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--who", required=True)
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--reason", default="")
    ap.add_argument("--purpose", choices=["interrupt", "reminder"], default="interrupt",
                    help="interrupt=未完成时主动让出前的提醒（>=5分钟）；reminder=一般提醒（>=1，不声称窗口满足）")
    ap.add_argument("--round", default="")
    ap.add_argument("--me-prefix", default="")
    ap.add_argument("--watch-files", action="append", default=[])
    ap.add_argument("--basis", default="")
    ap.add_argument("--basis-file", default="")
    a = ap.parse_args()

    if not os.path.isdir(a.dir) or not re.fullmatch(r"[A-Za-z0-9_-]+", a.who):
        out({"event": "REFUSED", "reason": "invalid-shared-dir-or-who"})
        return 1
    root_abs = os.path.realpath(a.dir)
    try:
        paths = a.watch_files + ([a.basis_file] if a.basis_file else [])
        if any(os.path.commonpath([root_abs, os.path.realpath(os.path.join(root_abs, f))]) != root_abs for f in paths):
            raise ValueError("path outside shared root")
    except ValueError:
        out({"event": "REFUSED", "reason": "path-outside-shared-root"})
        return 1
    if a.cmd == "arm" and a.purpose == "interrupt":
        if (not a.round.strip() or not re.fullmatch(r"[A-Za-z0-9_]+", a.me_prefix) or
            not a.watch_files or not (a.basis.strip() or a.basis_file)):
            out({"event": "REFUSED", "reason": "interrupt-requires-round-prefix-watch-set-and-basis"})
            return 1

    p = plan_path(a.dir, a.who)
    lk = PlanLock(a.dir, a.who)

    def begin():
        ok, why = lk.acquire()
        if not ok:
            payload = {"event": why if why == "STALE_LOCK_SUSPECT" else "LOCK_BUSY"}
            if lk.note:
                payload.update(lk.note)
            if why == "LOCK_BUSY":
                payload["action"] = "另一进程正在改同一计划；请稍后重试（本次未执行任何写入）"
            out(payload)
            return None, None
        st = load(p)
        if st is None:
            lk.release()
            out({"event": "STATE_UNREADABLE", "action": "计划文件解码失败；不写入、不给结论"})
            return None, None
        return st, (st.get("_ver") or 0)

    def commit(st, ver, event, extra=None):
        cur = load(p)
        if cur is None or (cur.get("_ver") or 0) != ver:
            out({"event": "CONFLICT", "expected_ver": ver, "disk_ver": (cur or {}).get("_ver"),
                 "action": "锁内版本校验失败（并发/陈旧快照）；本次写入已拒绝"})
            return 4
        new = dict(st)
        new["_ver"] = ver + 1
        save(p, new)
        payload = {"event": event, "ver": new["_ver"]}
        if extra:
            payload.update(extra)
        out(payload)
        return 0

    try:
        if a.cmd == "arm":
            st, ver = begin()
            if st is None:
                return 1
            try:
                if st.get("status") == "armed":
                    out({"event": "ALREADY_ARMED", "plan_id": st.get("plan_id"), "due_at": st.get("due_at")})
                    return 0
                floor = INTERRUPT_MIN if a.purpose == "interrupt" else MIN_MINUTES
                if a.minutes < floor:
                    out({"event": "REFUSED",
                         "reason": "--minutes 必须 >= %d（purpose=%s，收到 %d）" % (floor, a.purpose, a.minutes)})
                    return 1
                watch = [norm_rel(a.dir, os.path.join(a.dir, f)) for f in a.watch_files]
                snaps, problems = {}, []
                for rel in watch:
                    fp = os.path.join(a.dir, rel)
                    ok, text, err = read_once(fp)
                    if not ok:
                        problems.append({"file": rel, "error": err})
                        continue
                    snaps[rel] = attribution.snapshot(text)
                bf = norm_rel(a.dir, os.path.join(a.dir, a.basis_file)) if a.basis_file else ""
                bf_ok, bf_text, bf_err = (True, "", "")
                bf_hash = ""
                if bf:
                    bf_ok, bf_text, bf_err = read_once(os.path.join(a.dir, bf))
                    bf_hash = sha_bytes(bf_text.encode("utf-8")) if bf_ok else ""
                due_epoch = time.time() + a.minutes * 60
                newst = {
                    "_ver": ver, "plan_id": "plan-%s" % uuid.uuid4().hex[:8],
                    "prev_plan_id": st.get("plan_id", ""), "who": a.who,
                    "round": a.round, "purpose": a.purpose, "status": "armed",
                    "armed_at": nowstr(),
                    "due_epoch": due_epoch,
                    "due_at": datetime.fromtimestamp(due_epoch).strftime("%Y-%m-%d %H:%M:%S"),
                    "minutes": a.minutes, "reason": a.reason, "renewals": 0,
                    "me_prefix": a.me_prefix, "watch_files": watch,
                    "snapshots": snaps, "snapshot_ids": sorted(
                        {i for s in snaps.values() for i in s.get("ids", [])}),
                    "basis": a.basis, "basis_file": bf, "basis_hash": bf_hash,
                    "history": (st.get("history") or []) +
                               [{"at": nowstr(), "act": "arm", "reason": a.reason, "basis": a.basis,
                                 "purpose": a.purpose}],
                }
                rc = commit(newst, ver, "ARMED",
                            {"plan_id": newst["plan_id"], "due_at": newst["due_at"],
                             "watch_files": watch, "basis": a.basis})
                if rc == 0:
                    if problems or not bf_ok:
                        out({"event": "ARM_WARN", "problems": problems,
                             "basis_problem": (bf_err if bf and not bf_ok else ""),
                             "note": "登记时有文件不可读 ⇒ 到期 check 将以 READ_ERROR 阻塞，不会给结论"})
                    out({"note": "计划期间继续做不依赖他人的事（M6）；他方消息/主人指令/本人新工作/新缺陷 -> 立刻 cancel",
                         "scope_caveat": "M1 是中断前的延迟检查：不得因『无独立工作』而 arm 退出；"
                                         "用户明确的『继续等待』指令优先于本机制"})
                return rc
            finally:
                lk.release()

        if a.cmd == "cancel":
            st, ver = begin()
            if st is None:
                return 1
            try:
                if st.get("status") != "armed":
                    out({"event": "NOTHING_TO_CANCEL", "status": st.get("status", "none")})
                    return 0
                newst = dict(st)
                newst["status"] = "cancelled"
                newst.setdefault("history", []).append(
                    {"at": nowstr(), "act": "cancel", "reason": a.reason})
                return commit(newst, ver, "CANCELLED", {"plan_id": st.get("plan_id")})
            finally:
                lk.release()

        if a.cmd == "renew":
            st, ver = begin()
            if st is None:
                return 1
            try:
                if st.get("status") != "armed":
                    out({"event": "NOT_ARMED", "status": st.get("status", "none")})
                    return 0
                if (st.get("renewals") or 0) >= MAX_RENEW:
                    out({"event": "RENEW_LIMIT", "renewals": st["renewals"],
                         "note": "已达上限 %d 次：不得再续，须报主人裁决；仍须继续已授权的必要工作" % MAX_RENEW})
                    return 0
                r = (a.reason or "").strip()
                if r in WEAK_REASONS or len(r) < 6:
                    out({"event": "REFUSED", "reason": "续期理由为空话或过短（'再等等'不算）；须写明新依据"})
                    return 1
                purpose = st.get("purpose", "interrupt")
                floor = INTERRUPT_MIN if purpose == "interrupt" else MIN_MINUTES
                if a.minutes < floor:
                    out({"event": "REFUSED", "reason": "renew 也须校验时长：>= %d（purpose=%s，收到 %d）"
                                                       % (floor, purpose, a.minutes)})
                    return 1
                newst = dict(st)
                newst["renewals"] = (st.get("renewals") or 0) + 1
                newst["due_epoch"] = time.time() + a.minutes * 60
                newst["due_at"] = datetime.fromtimestamp(
                    newst["due_epoch"]).strftime("%Y-%m-%d %H:%M:%S")
                newst.setdefault("history", []).append({"at": nowstr(), "act": "renew", "reason": r})
                return commit(newst, ver, "RENEWED",
                              {"renewals": newst["renewals"], "due_at": newst["due_at"]})
            finally:
                lk.release()

        if a.cmd in ("status", "check"):
            st, ver = begin()
            if st is None:
                return 1
            if a.cmd == "status":
                out({"event": "STATUS", "plan": st})
                return 0
            if st.get("status") != "armed":
                out({"event": "NOT_ARMED", "status": st.get("status", "none")})
                return 0
            try:
                due = float(st["due_epoch"])
                if not (0 < due < float('inf')):
                    raise ValueError('invalid deadline')
            except Exception:
                out({"event": "BAD_DUE", "plan_id": st.get("plan_id")})
                return 1
            if due > time.time():
                out({"event": "WAITING", "due_at": st["due_at"], "plan_id": st.get("plan_id")})
                return 0

            me = (st.get("me_prefix") or "").lower()
            other_hits, mine_hits, unknown, problems = scan_activity(
                st, a.dir, me, DEFAULT_IGNORE)

            # 依据文件：未取得证据 ⇒ 不得判"依据未变"
            basis_state, basis_err = "unchanged", ""
            if st.get("basis_file"):
                ok, text, err = read_once(os.path.join(a.dir, st["basis_file"]))
                if not ok:
                    basis_state, basis_err = "unverified", err
                elif not st.get("basis_hash"):
                    basis_state, basis_err = "unverified", "no-baseline-hash"
                elif sha_bytes(text.encode("utf-8")) != st["basis_hash"]:
                    basis_state = "changed"

            if problems:
                out({"event": "READ_ERROR", "problems": problems,
                     "action": "必需监测文件缺失/不可读 ⇒ 无证据 ⇒ 不得判『未发现他方活动』（BLOCKED）"})
                return 2
            if basis_state == "unverified":
                out({"event": "BASIS_UNVERIFIED", "basis_file": st.get("basis_file"), "error": basis_err,
                     "action": "依据不可核对 ⇒ 不得给收尾结论（BLOCKED）"})
                return 2
            if other_hits:
                out({"event": "DUE_BUT_BLOCKED", "reason": "armed 之后出现他方可归属的变化",
                     "files": other_hits, "action": "先 cancel 并处理该消息"})
                return 2
            if basis_state == "changed":
                out({"event": "BASIS_CHANGED", "basis_file": st.get("basis_file"),
                     "note": "依据已变，须复核『我已无独立可做的事』是否仍成立"})
                return 2
            if unknown:
                out({"event": "DUE_BUT_BLOCKED", "reason": "载体已变化但无法归属（含署名行更新）",
                     "changed_files": unknown[:10],
                     "action": "保守处理：不给结论；人工核对后决定 cancel 或收尾"})
                return 2
            out({"event": "TIMER_ELAPSED", "due_at": st["due_at"], "who": st.get("who"),
                 "plan_id": st.get("plan_id"), "round": st.get("round"), "purpose": st.get("purpose"),
                 "checked_files": st.get("watch_files") or [], "basis_state": basis_state,
                 "mine_only_files": mine_hits,
                 "note_mine": ("本方单独追加的消息未计入阻塞" if mine_hits else ""),
                 "note": "仅为『计时已到 ＋ 未发现他方可归属活动 ＋ 依据可核对且未变』的**事实**；"
                         "不是收尾许可。仍须核对references/liveness.md的承诺、点名请求及收尾检查"
                         "并确认无『用户继续等待』指令与『有人在等我』；不通过则转『阻塞登记 + 恢复条件』",
                 "caveat": "手动原型：无消息监听、无定时调度；未实测多进程压力与重启恢复"})
            return 0
    finally:
        lk.release()


if __name__ == "__main__":
    sys.exit(main())
