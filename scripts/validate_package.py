#!/usr/bin/env python3
"""Read-only checks for the full repository, not a runtime installation."""
import argparse
import ast
from pathlib import Path
import re
import sys


def validate(root):
    failures = []
    for name in ('VERSION', 'SKILL.md', 'README.md', 'CHANGELOG.md', 'AGENTS.md',
                 'CONTRIBUTING.md', 'references/runtime.md', 'docs/quickstart.md',
                 'docs/tools.md', 'docs/troubleshooting.md', 'scripts/attribution.py',
                 'scripts/quiet_window_watch.py', 'scripts/shutdown_plan.py', 'tests/test_runtime.py'):
        if not (root / name).is_file():
            failures.append('missing: ' + name)
    if failures:
        return failures, 0
    version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    skill = (root / 'SKILL.md').read_text(encoding='utf-8')
    front = re.match(r'^---\n(.*?)\n---\n', skill.replace('\r\n', '\n'), re.S)
    if not front or not re.search(r'^name: ai-collaboration$', front[1], re.M) or not re.search(r'^description: \S', front[1], re.M):
        failures.append('invalid SKILL frontmatter')
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version) or f'version: "{version}"' not in skill:
        failures.append('VERSION/SKILL mismatch')
    for name in ('README.md', 'CHANGELOG.md'):
        if version not in (root / name).read_text(encoding='utf-8'):
            failures.append('version missing: ' + name)
    count = 0
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if any(x in ('.git', '__pycache__', '.baton-state', '.state') for x in rel.parts) or not p.is_file():
            continue
        if p.suffix not in ('.md', '.py') and p.name not in ('VERSION', '.gitignore'):
            continue
        count += 1
        raw = p.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            failures.append('not UTF-8: ' + str(rel))
            continue
        if raw.startswith(b'\xef\xbb\xbf') or '\ufffd' in text or any(ord(c) < 32 and c not in '\r\n\t' or ord(c) == 127 for c in text):
            failures.append('encoding/control character: ' + str(rel))
        if re.search(r'\r(?!\n)', text):
            failures.append('bare CR: ' + str(rel))
        if p.suffix == '.py':
            try:
                ast.parse(text, filename=str(rel), feature_version=(3, 9))
            except SyntaxError:
                failures.append('Python 3.9 grammar: ' + str(rel))
        if p.suffix == '.md':
            prose = re.sub(r'^```[^\n]*\n.*?^```\s*$', '', text, flags=re.M | re.S)
            for target in re.findall(r'\[[^\]\n]+\]\(([^)]+)\)', prose):
                if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
                    continue
                local = target.split('#')[0].strip('<>')
                if local and not (p.parent / local).exists():
                    failures.append('broken link: ' + str(rel) + ' -> ' + target)
        if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY', text):
            failures.append('possible credential: ' + str(rel))
    return failures, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    failures, count = validate(args.root)
    for failure in failures:
        print(failure)
    print(f'{"FAILED" if failures else "OK"}: {count} text files checked; grammar check is not Python 3.9 runtime testing')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
