import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_resume.py'


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = {'schema': 1, 'party': 'tester', 'round': 'R-test', 'status': 'active',
                      'verified_state': 'review done', 'independent_work': 'fix remaining issue',
                      'next_action': 'review changed files', 'waiting_for': 'none', 'limitations': 'no wake tested',
                      'entry': 'entry.md', 'task_state': 'state.md', 'handoff': 'handoff.md',
                      'cursor': {'file': 'topic.md', 'id': 'test-001'}, 'sha256': {}}
        for name in ('entry.md', 'state.md', 'handoff.md', 'topic.md'):
            data = b'[2026-10-05 12:00:00] tester -> reviewer: [id=test-001] [type=ACCEPT] accepted' if name == 'topic.md' else b'current task'
            (self.root / name).write_bytes(data)
            self.state['sha256'][name] = hashlib.sha256(data).hexdigest()

    def run_check(self, expected, event, party='tester', round_id='R-test', raw=None):
        (self.root / 'checkpoint.json').write_text(json.dumps(self.state) if raw is None else raw, encoding='utf-8')
        before = (self.root / 'checkpoint.json').read_bytes()
        result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root),
                                 '--checkpoint', 'checkpoint.json', '--party', party, '--round', round_id],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(expected, result.returncode, result.stderr + result.stdout)
        self.assertEqual(event, json.loads(result.stdout)['event'])
        self.assertEqual(before, (self.root / 'checkpoint.json').read_bytes())
        return json.loads(result.stdout)

    def test_new_process_and_complete_status_never_prove_completion(self):
        self.run_check(0, 'RESUME_READY')
        self.state['status'] = 'complete'
        self.assertFalse(self.run_check(0, 'RESUME_READY')['completion_verified'])

    def test_new_instruction_and_topic_increment_require_refresh(self):
        for name in ('state.md', 'topic.md'):
            with self.subTest(name=name):
                original = (self.root / name).read_bytes()
                (self.root / name).write_bytes(original + b' new user instruction')
                self.run_check(2, 'REFRESH_REQUIRED')
                (self.root / name).write_bytes(original)

    def test_missing_summary_or_handoff_blocks_recovery(self):
        for name in ('state.md', 'handoff.md'):
            original = (self.root / name).read_bytes()
            (self.root / name).unlink()
            self.run_check(1, 'RECOVERY_BLOCKED')
            (self.root / name).write_bytes(original)

    def test_wrong_identity_round_and_cursor(self):
        self.run_check(1, 'RECOVERY_BLOCKED', party='other')
        self.run_check(1, 'RECOVERY_BLOCKED', round_id='old')
        self.state['cursor']['id'] = 'absent'
        self.run_check(1, 'RECOVERY_BLOCKED')

    def test_duplicate_cursor_does_not_skip_messages(self):
        (self.root / 'topic.md').write_text('[now] tester -> reviewer: [id=test-001] [type=ACCEPT] first\n[now] tester -> reviewer: [id=test-001] [type=RESULT] duplicate', encoding='utf-8')
        self.run_check(1, 'RECOVERY_BLOCKED')

    def test_corrupt_and_incomplete_checkpoint_is_preserved(self):
        for raw in ('{', '[]', '{"schema": true}', '{"schema": 1.0}', 'null'):
            self.run_check(1, 'RECOVERY_BLOCKED', raw=raw)
        self.state.pop('next_action')
        self.run_check(1, 'RECOVERY_BLOCKED')

    def test_body_reference_is_not_cursor_or_duplicate(self):
        topic = self.root / 'topic.md'
        original = topic.read_bytes()
        topic.write_bytes(b'example [id=test-001] only')
        self.run_check(1, 'RECOVERY_BLOCKED')
        data = original + b'\nbody refers to [id=test-001]'
        topic.write_bytes(data)
        self.state['sha256']['topic.md'] = hashlib.sha256(data).hexdigest()
        self.run_check(0, 'RESUME_READY')
        topic.write_bytes(b'```example\n' + original + b'\n```')
        self.state['sha256']['topic.md'] = hashlib.sha256(topic.read_bytes()).hexdigest()
        self.run_check(1, 'RECOVERY_BLOCKED')

    def test_outside_path_and_bad_fingerprint(self):
        self.state['entry'] = '../outside.md'
        self.run_check(1, 'RECOVERY_BLOCKED')
        self.state['entry'] = 'entry.md'
        self.state['sha256']['entry.md'] = 'not a hash'
        self.run_check(1, 'RECOVERY_BLOCKED')


if __name__ == '__main__':
    unittest.main()
