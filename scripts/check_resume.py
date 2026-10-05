#!/usr/bin/env python3
"""Read-only recovery checkpoint validation; never runs or wakes a model."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from attribution import parse_blocks


def check(root, checkpoint, party, round_id):
    root = root.resolve()
    def local(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('missing path')
        raw = Path(value)
        if raw.is_absolute() or '..' in raw.parts:
            raise ValueError('path must be relative inside shared root')
        path = (root / raw).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError('missing or outside-root file')
        return path
    try:
        state = json.loads(local(checkpoint).read_text(encoding='utf-8'))
        if not isinstance(state, dict) or type(state.get('schema')) is not int or state['schema'] != 1:
            raise ValueError('invalid schema')
        if not party or not round_id or state.get('party') != party or state.get('round') != round_id:
            raise ValueError('party/round mismatch')
        for key in ('verified_state', 'independent_work', 'next_action', 'waiting_for', 'limitations'):
            if not isinstance(state.get(key), str) or not state[key].strip():
                raise ValueError('missing field: ' + key)
        if state.get('status') not in ('active', 'waiting', 'complete', 'cancelled'):
            raise ValueError('invalid status')
        paths = [local(state.get(key)) for key in ('entry', 'task_state', 'handoff')]
        cursor = state.get('cursor')
        if not isinstance(cursor, dict) or not isinstance(cursor.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_\-]+', cursor['id']):
            raise ValueError('invalid cursor')
        topic = local(cursor.get('file'))
        paths.append(topic)
        raw_files = {path: path.read_bytes() for path in paths}
        text = raw_files[topic].decode('utf-8')
        # Full message headers inside fenced examples are not live cursors.
        lines, fence = [], None
        for line in text.splitlines():
            marker = re.match(r'^\s*(`{3,}|~{3,})', line)
            if marker:
                token = marker[1]
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = None
                continue
            if fence is None:
                lines.append(line)
        if sum(msg_id == cursor['id'] for msg_id, _ in parse_blocks('\n'.join(lines))[1]) != 1:
            raise ValueError('cursor absent or duplicated; reread relevant messages')
        fingerprints = state.get('sha256')
        if not isinstance(fingerprints, dict):
            raise ValueError('missing fingerprints')
        changed = []
        for path in paths:
            rel = path.relative_to(root).as_posix()
            expected = fingerprints.get(rel)
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
                raise ValueError('missing/invalid fingerprint: ' + rel)
            if hashlib.sha256(raw_files[path]).hexdigest() != expected:
                changed.append(rel)
        if changed:
            return {'event': 'REFRESH_REQUIRED', 'changed': changed, 'instruction': 'reread state and messages before acting'}, 2
        return {'event': 'RESUME_READY', 'status': state['status'], 'next_action': state['next_action'], 'completion_verified': False}, 0
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        return {'event': 'RECOVERY_BLOCKED', 'reason': str(exc), 'original_preserved': True}, 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--checkpoint', required=True)
    parser.add_argument('--party', required=True)
    parser.add_argument('--round', dest='round_id', required=True)
    args = parser.parse_args()
    result, code = check(args.root, args.checkpoint, args.party, args.round_id)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
