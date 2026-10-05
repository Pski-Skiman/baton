import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import attribution
import quiet_window_watch as watch
import shutdown_plan as plan


def message(prefix, number, body='content'):
    return f'[2026-10-05 00:00:00] {prefix} -> all: [id={prefix}-{number}] [type=NOTICE]\n{body}\n'


def run_main(module, args):
    out = io.StringIO()
    with patch.object(sys, 'argv', [module.__file__] + args), contextlib.redirect_stdout(out):
        rc = module.main()
    return rc, [json.loads(x) for x in out.getvalue().splitlines()]


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.text = 'intro\n' + message('other', 1)
        self.base = attribution.snapshot(self.text)

    def verdict(self, new):
        return attribution.compare(self.base, new, 'me')['verdict']

    def test_own_append_and_other_append(self):
        self.assertEqual(self.verdict(self.text + message('me', 2)), 'mine')
        self.assertEqual(self.verdict(self.text + message('other', 2)), 'other')

    def test_mixed_unlabelled_change_not_hidden(self):
        self.assertEqual(self.verdict(self.text.replace('intro', 'progress') + message('me', 2)), 'unknown')

    def test_reorder_not_unchanged(self):
        text = message('me', 1) + message('me', 2)
        self.assertEqual(attribution.compare(attribution.snapshot(text), message('me', 2) + message('me', 1), 'me')['verdict'], 'unknown')

    def test_duplicate_id_not_own_append(self):
        self.assertNotEqual(self.verdict(self.text + message('me', 2) * 2), 'mine')

    def test_whitespace_and_body_examples_not_unchanged(self):
        self.assertEqual(self.verdict(self.text + '  '), 'unknown')
        text = self.text + 'example [id=me-fake] [type=NOTICE]\n'
        self.assertNotIn('me-fake', attribution.snapshot(text)['ids'])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.file = self.root / 'topic.md'
        self.file.write_text('intro\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, cmd, *extra):
        args = [cmd, '--dir', str(self.root), '--who', 'tester']
        if cmd == 'arm':
            args += ['--round', 'R-test', '--me-prefix', 'me', '--watch-files', 'topic.md', '--basis', 'items closed']
        return args + list(extra)

    def arm_due(self):
        self.assertEqual(run_main(plan, self.args('arm'))[0], 0)
        p = Path(plan.plan_path(str(self.root), 'tester'))
        state = json.loads(p.read_text(encoding='utf-8'))
        state['due_at'] = '2000-01-01 00:00:00'
        state['due_epoch'] = 946684800
        p.write_text(json.dumps(state), encoding='utf-8')
        return p

    def test_invalid_owner_no_identity_collision(self):
        self.assertNotEqual(plan.plan_path(str(self.root), 'a-b'), plan.plan_path(str(self.root), 'ab'))
        self.assertEqual(run_main(plan, self.args('status', '--who', '../bad'))[0], 1)

    def test_incomplete_interrupt_refused(self):
        rc, events = run_main(plan, ['arm', '--dir', str(self.root), '--who', 'tester'])
        self.assertEqual(rc, 1)
        self.assertEqual(events[0]['event'], 'REFUSED')

    def test_outside_root_refused(self):
        self.assertEqual(run_main(plan, self.args('arm', '--watch-files', '../outside.md'))[0], 1)
        self.assertEqual(run_main(watch, ['--dir', str(self.root), '--me', 'me', '--files', '../outside.md'])[0], 1)

    def test_missing_file_blocks_and_cancel_is_terminal(self):
        self.arm_due()
        self.file.unlink()
        rc, events = run_main(plan, self.args('check'))
        self.assertEqual(rc, 2)
        self.assertEqual(events[-1]['event'], 'READ_ERROR')
        run_main(plan, self.args('cancel', '--reason', 'new work'))
        self.assertEqual(run_main(plan, self.args('renew', '--reason', 'a concrete reason'))[1][-1]['event'], 'NOT_ARMED')

    def test_negative_renew_refused_without_change(self):
        p = self.arm_due()
        before = p.read_bytes()
        self.assertEqual(run_main(plan, self.args('renew', '--minutes', '-1', '--reason', 'concrete dependency'))[0], 1)
        self.assertEqual(before, p.read_bytes())

    def test_fractional_deadline_not_rounded_early(self):
        run_main(plan, self.args('arm'))
        p = Path(plan.plan_path(str(self.root), 'tester'))
        state = json.loads(p.read_text(encoding='utf-8'))
        state['due_epoch'] = 1000.75
        p.write_text(json.dumps(state), encoding='utf-8')
        with patch.object(plan.time, 'time', return_value=1000.5):
            self.assertEqual(run_main(plan, self.args('check'))[1][-1]['event'], 'WAITING')

    def test_nested_basis_preserved_and_changed_basis_blocks(self):
        nested = self.root / 'sub' / 'basis.md'
        nested.parent.mkdir()
        nested.write_text('closed', encoding='utf-8')
        run_main(plan, self.args('arm', '--basis-file', 'sub/basis.md'))
        p = Path(plan.plan_path(str(self.root), 'tester'))
        state = json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(state['basis_file'], 'sub/basis.md')
        state['due_epoch'] = 946684800
        p.write_text(json.dumps(state), encoding='utf-8')
        nested.write_text('new work', encoding='utf-8')
        rc, events = run_main(plan, self.args('check'))
        self.assertEqual(rc, 2)
        self.assertEqual(events[-1]['event'], 'BASIS_CHANGED')

    def test_corrupt_state_not_empty_status(self):
        p = Path(plan.plan_path(str(self.root), 'tester'))
        for value in ('broken', '[]', '{"history": 1}'):
            p.write_text(value, encoding='utf-8')
            rc, events = run_main(plan, self.args('status'))
            self.assertEqual(rc, 1)
            self.assertEqual(events[-1]['event'], 'STATE_UNREADABLE')

    def test_restored_empty_interrupt_set_refused(self):
        p = self.arm_due()
        state = json.loads(p.read_text(encoding='utf-8'))
        state.update(watch_files=[], snapshots={})
        p.write_text(json.dumps(state), encoding='utf-8')
        before = p.read_bytes()
        rc, events = run_main(plan, self.args('check'))
        self.assertEqual((rc, events[-1]['event']), (1, 'STATE_UNREADABLE'))
        self.assertEqual(before, p.read_bytes())

    def test_restored_watch_and_basis_paths_refused_before_read(self):
        p = self.arm_due()
        state = json.loads(p.read_text(encoding='utf-8'))
        for field in ('watch_files', 'basis_file'):
            broken = dict(state)
            broken[field] = ['../outside.md'] if field == 'watch_files' else '../outside.md'
            if field == 'watch_files':
                broken['snapshots'] = {'../outside.md': state['snapshots']['topic.md']}
            p.write_text(json.dumps(broken), encoding='utf-8')
            with patch.object(plan, 'read_once', side_effect=AssertionError('must not read watched paths')):
                rc, events = run_main(plan, self.args('check'))
            self.assertEqual((rc, events[-1]['event']), (1, 'STATE_PATH_OUTSIDE_ROOT'))

    def test_restored_schema_corruption_is_structured_error(self):
        p = self.arm_due()
        original = json.loads(p.read_text(encoding='utf-8'))
        variants = []
        missing_display = dict(original)
        missing_display.pop('due_at')
        variants.append(missing_display)
        for key, value in (('_ver', -1), ('renewals', True), ('due_epoch', float('nan')),
                           ('me_prefix', []), ('status', 'invented')):
            variants.append(dict(original, **{key: value}))
        broken_snapshot = json.loads(json.dumps(original))
        broken_snapshot['snapshots']['topic.md']['blocks'] = {'bad-id': 3}
        variants.append(broken_snapshot)
        for state in variants:
            with self.subTest(state=state):
                p.write_text(json.dumps(state), encoding='utf-8')
                rc, events = run_main(plan, self.args('check'))
                self.assertEqual((rc, events[-1]['event']), (1, 'STATE_UNREADABLE'))

    def test_restored_owner_mismatch_refused(self):
        p = self.arm_due()
        state = json.loads(p.read_text(encoding='utf-8'))
        state['who'] = 'someone-else'
        p.write_text(json.dumps(state), encoding='utf-8')
        rc, events = run_main(plan, self.args('status'))
        self.assertEqual((rc, events[-1]['event']), (1, 'STATE_OWNER_MISMATCH'))

    def test_reminder_without_watch_is_only_reminder(self):
        rc, _ = run_main(plan, ['arm', '--dir', str(self.root), '--who', 'tester',
                               '--purpose', 'reminder', '--minutes', '1'])
        self.assertEqual(rc, 0)
        p = Path(plan.plan_path(str(self.root), 'tester'))
        state = json.loads(p.read_text(encoding='utf-8'))
        state['due_epoch'] = 946684800
        p.write_text(json.dumps(state), encoding='utf-8')
        rc, events = run_main(plan, self.args('check'))
        self.assertEqual((rc, events[-1]['event']), (0, 'TIMER_ELAPSED'))
        self.assertEqual(events[-1]['purpose'], 'reminder')
        self.assertEqual(events[-1]['checked_files'], [])

    def test_stale_foreign_and_malformed_lock_preserved(self):
        lock = plan.PlanLock(str(self.root), 'tester')
        self.assertTrue(lock.acquire(tries=1)[0])
        other = plan.PlanLock(str(self.root), 'tester')
        with patch.object(plan.time, 'time', return_value=10**12):
            self.assertEqual(other.acquire(tries=1)[1], 'STALE_LOCK_SUSPECT')
        Path(lock.p).write_text('{"token":"foreign"}', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            lock.release()
        self.assertTrue(Path(lock.p).exists())
        for value in ('[]', '{"at":"bad"}', '{"at": -Infinity}', '{"at": true}', 'broken'):
            Path(lock.p).write_text(value, encoding='utf-8')
            self.assertEqual(other.acquire(tries=1)[1], 'STALE_LOCK_SUSPECT')
            self.assertEqual(Path(lock.p).read_text(encoding='utf-8'), value)

    def test_check_obeys_plan_lock(self):
        self.arm_due()
        holder = plan.PlanLock(str(self.root), 'tester')
        self.assertTrue(holder.acquire(tries=1)[0])
        with patch.object(plan.time, 'sleep'):
            rc, events = run_main(plan, self.args('check'))
        self.assertEqual(rc, 1)
        self.assertEqual(events[-1]['event'], 'LOCK_BUSY')
        holder.release()

    def test_actual_process_cancel_renew(self):
        self.arm_due()
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
        procs = [subprocess.Popen([sys.executable, plan.__file__] + self.args(cmd, '--reason', 'new concrete dependency'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env) for cmd in ('cancel', 'renew')]
        for proc in procs:
            stdout, stderr = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, (stdout, stderr))
            self.assertEqual(stderr, '')
        self.assertEqual(plan.load(plan.plan_path(str(self.root), 'tester'))['status'], 'cancelled')

    def test_window_parameters_and_empty_set(self):
        for key in ('--window', '--interval', '--max-minutes'):
            rc, _ = run_main(watch, ['--dir', str(self.root), '--me', 'me', key, '0'])
            self.assertEqual(rc, 1)
        self.file.unlink()
        self.assertEqual(run_main(watch, ['--dir', str(self.root), '--me', 'me'])[0], 1)

    def watched(self, change, limit=1):
        clock = [0]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] == 1:
                change()
        with patch.object(watch.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(watch.time, 'sleep', side_effect=sleep):
            return run_main(watch, ['--dir', str(self.root), '--me', 'me', '--files', 'topic.md', '--window', '2', '--interval', '1', '--max-minutes', str(limit)])

    def test_own_only_window_and_mixed_reset(self):
        rc, events = self.watched(lambda: self.file.write_text('intro\n' + message('me', 1), encoding='utf-8'))
        self.assertEqual(rc, 0)
        self.assertEqual(events[-1]['event'], 'WINDOW_SATISFIED')
        self.assertNotIn('QUIET', [e['event'] for e in events])
        self.file.write_text('intro\n', encoding='utf-8')
        rc, events = self.watched(lambda: self.file.write_text('changed\n' + message('me', 1), encoding='utf-8'))
        self.assertIn('UNATTRIBUTED', [e['event'] for e in events])
        # After observing the mixed change the next full quiet window is still valid.
        self.assertEqual(rc, 0)
        self.assertGreaterEqual(events[-1]['quiet_sec'], 2)

    def test_unreadable_never_satisfies_window(self):
        rc, events = self.watched(self.file.unlink)
        self.assertEqual(rc, 2)
        self.assertNotIn('WINDOW_SATISFIED', [e['event'] for e in events])


if __name__ == '__main__':
    unittest.main()
