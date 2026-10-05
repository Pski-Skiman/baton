#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative attribution of append-only collaboration messages."""
import hashlib
import re

ID_ANY_RE = re.compile(r"\[id=([A-Za-z0-9_\-]+)\]")


def sha16(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def prefix_of(msg_id):
    return (msg_id or "").split("-")[0].lower()


def parse_blocks(text):
    """切成 (preamble, blocks)；blocks = [(id, content)]，按出现顺序。"""
    pre, blocks = [], []
    cur_id, cur = None, []
    started = False
    for ln in text.split("\n"):
        m = ID_ANY_RE.search(ln) if re.match(r"^\[[^\]\r\n]+\]\s+.+(?:→|->).+\[type=", ln) else None
        if m:
            started = True
            if cur_id is not None:
                blocks.append((cur_id, "\n".join(cur).rstrip()))
            cur_id, cur = m.group(1), [ln]
        elif started:
            cur.append(ln)
        else:
            pre.append(ln)
    if cur_id is not None:
        blocks.append((cur_id, "\n".join(cur).rstrip()))
    return "\n".join(pre).rstrip(), blocks


def _map(blocks):
    d = {}
    for i, c in blocks:
        d.setdefault(i, []).append(sha16(c))
    return d


def snapshot(text):
    """基线：只存哈希（preamble 哈希 + 每块内容哈希），不存全文。"""
    pre, blocks = parse_blocks(text)
    return {"pre": sha16(pre), "blocks": _map(blocks),
            "length": len(text), "text_hash": sha16(text),
            "order": [i for i, _ in blocks],
            "ids": sorted({i for i, _ in blocks if i})}


def compare(snap, text_now, me, ignore=frozenset()):
    """把 now 与基线比对，返回归属判定。"""
    me = (me or "").lower()
    ignore = set(x.lower() for x in (ignore or ()))

    pre1, blocks1 = parse_blocks(text_now)
    m0 = snap.get("blocks") or {}
    m1 = _map(blocks1)
    ids0, ids1 = set(m0), set(m1)

    new_ids = ids1 - ids0
    removed = sorted(ids0 - ids1)

    def is_mine(i):
        return prefix_of(i) == me

    def is_ignored(i):
        return prefix_of(i) in ignore

    other_new = sorted(i for i in new_ids if not is_mine(i) and not is_ignored(i))
    mine_new = sorted(i for i in new_ids if is_mine(i))
    ignored_new = sorted(i for i in new_ids if is_ignored(i))

    changed_other, changed_mine, changed_any = [], [], []
    for i in (ids0 & ids1):
        if m0[i] != m1[i]:
            changed_any.append(i)
            if is_mine(i):
                changed_mine.append(i)
            elif not is_ignored(i):
                changed_other.append(i)

    preamble_changed = (snap.get("pre") != sha16(pre1))
    order = [i for i, _ in blocks1]
    duplicate = len(order) != len(set(order)) or any(len(v) != 1 for v in m0.values())
    original_order = snap.get("order")
    reordered = original_order is None or [i for i in order if i in ids0] != original_order
    old_length = snap.get("length")
    prefix_unchanged = isinstance(old_length, int) and sha16(text_now[:old_length]) == snap.get("text_hash")
    raw_changed = sha16(text_now) != snap.get("text_hash")

    # 判定顺序：other 优先 → 未知保守 → mine
    if other_new or changed_other:
        verdict = "other"
    elif duplicate or reordered or preamble_changed or removed or changed_any or ignored_new:
        verdict = "unknown"
    elif mine_new and prefix_unchanged:
        verdict = "mine"
    elif raw_changed:
        verdict = "unknown"
    else:
        verdict = "unchanged"

    return {
        "verdict": verdict,
        "other_new": other_new, "mine_new": mine_new, "ignored_new": ignored_new,
        "changed_other": sorted(changed_other), "changed_mine": sorted(changed_mine),
        "changed_any_existing": sorted(changed_any),
        "removed": removed, "preamble_changed": preamble_changed,
        "why": ("他方新增块/他方块被改" if verdict == "other" else
                "preamble变/块被删/既有块被改/占位块出现 ⇒ 差分无法全部归属本方" if verdict == "unknown" else
                "全部差分可归属本方（仅新增本方块）" if verdict == "mine" else "无差分"),
    }
