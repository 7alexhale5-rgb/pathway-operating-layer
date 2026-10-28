"""Security regressions use the production module, never the approval fixture harness."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / 'scripts/operating-layer.py'
spec = importlib.util.spec_from_file_location('security_engine', SOURCE)
engine = importlib.util.module_from_spec(spec)
if os.environ.get('SECURITY_TEST_BASELINE'):
    code = subprocess.check_output(['git', '-C', str(REPO), 'show', 'HEAD:scripts/operating-layer.py'])
    exec(compile(code, str(SOURCE), 'exec'), engine.__dict__)
else:
    spec.loader.exec_module(engine)


class SecurityCorrections(unittest.TestCase):
    def test_test_shaped_path_never_grants_authority(self):
        with tempfile.TemporaryDirectory(prefix='operating-layer-test-', dir='/private/tmp') as folder:
            root = Path(folder) / 'out'
            root.mkdir()
            paths = SimpleNamespace(output_root_input=root,
                                    approvals_path=root / 'operator-intelligence/approvals.ndjson')
            self.assertTrue(engine.approval_store_is_protected(paths))

    def test_protected_credit_held_even_when_os_ledger_is_readable(self):
        with mock.patch.object(engine, '_authority_path_is_os_owned', return_value=True):
            events = engine.approval_events_for(SimpleNamespace())
        self.assertFalse(events.valid)
        self.assertEqual(events.error, 'fresh-authentication-unavailable')

    def test_real_cli_refuses_test_shaped_output_root(self):
        with tempfile.TemporaryDirectory(prefix='operating-layer-test-', dir='/private/tmp') as folder:
            root = Path(folder) / 'out'
            receipt = Path(folder) / 'release.json'
            receipt.write_text('{}')
            argv = ['approval-issue', '--output-root', str(root), '--work-id', 'work',
                    '--kind', engine.APPROVAL_KIND_RELEASE, '--reason', 'Reviewed',
                    '--release-receipt', str(receipt), '--json']
            paths = engine.Paths(engine.build_parser().parse_args(argv))
            paths.work_items_path.parent.mkdir(parents=True, exist_ok=True)
            paths.work_items_path.write_text(json.dumps({'work_id': 'work', 'project_name': 'project'}) + '\n')
            proc = subprocess.run([sys.executable, str(SOURCE), *argv], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('authority_command', json.loads(proc.stdout))
            self.assertFalse(paths.approvals_path.exists())

    def test_snapshot_executes_validated_bytes_despite_source_swap(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'verify.py'
            path.write_text('print("TRUSTED")\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            run = subprocess.run
            def swap(*args, **kwargs):
                path.write_text('print("SUBSTITUTED")\n')
                return run(*args, **kwargs)
            with mock.patch.object(engine.subprocess, 'run', side_effect=swap):
                result = engine.run_observability_verifier_argv(
                    [sys.executable, str(path)], folder, expected_verifier_sha256=digest,
                    trusted_sha256=[digest])
            self.assertEqual(result[0], 0)
            self.assertEqual(result[3].strip(), 'TRUSTED')

    def test_verifier_cannot_import_adjacent_or_pythonpath_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'verify.py'
            path.write_text('import json\nprint(json.dumps({"ok": True}))\n')
            (Path(folder) / 'json.py').write_text('raise RuntimeError("shadowed")\n')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with mock.patch.dict(os.environ, {'PYTHONPATH': folder}):
                result = engine.run_observability_verifier_argv(
                    [sys.executable, str(path)], folder, expected_verifier_sha256=digest,
                    trusted_sha256=[digest])
            self.assertEqual(result[0], 0)
            self.assertEqual(json.loads(result[3]), {'ok': True})

    def test_default_output_shows_authority_command_and_reason(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            engine.print_result({'findings': [{'message': 'authority held'}],
                                 'authority_command': 'sudo fixed-helper issue'})
        self.assertIn('sudo fixed-helper issue', output.getvalue())
        self.assertIn('authority held', output.getvalue())

    def test_provider_action_cannot_rescue_invalid_release_baton(self):
        baton = {'pathway': 'release', 'credits_pathway': True, 'proof_id': 'release',
                 'created_at': '2026-10-20', 'work_id': 'work'}
        proofs = [{'work_id': 'work', 'pathway': 'release', 'proof_id': 'provider',
                   'release_provider_action_contract': True}]
        paths = SimpleNamespace(proofs_path=Path('unused'))
        with mock.patch.object(engine, 'carry_forwards_for_work', return_value=[baton]), \
             mock.patch.object(engine, 'read_ndjson', return_value=proofs), \
             mock.patch.object(engine, 'approval_events_for', return_value=engine.ApprovalEvents([])), \
             mock.patch.object(engine, 'release_approval_corroborated', return_value=True):
            result = engine.latest_carry_forward_for_work(paths, 'work')
        self.assertIs(result.get('release_credit_current'), False)

    def test_approval_consumer_binds_markdown_and_executed_type(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder) / 'release.json'
            receipt.write_text('{"recommendation_id":"rec"}')
            evidence = Path(folder) / 'release.md'
            evidence.write_text('reviewed evidence')
            args = engine.build_parser().parse_args([
                'approval-issue', '--kind', engine.APPROVAL_KIND_RELEASE,
                '--work-id', 'work', '--reason', 'Reviewed', '--release-receipt', str(receipt),
                '--evidence', str(evidence), '--proof-type', 'executed'])
            paths = SimpleNamespace(approvals_path=Path(folder)/'approvals', work_items_path=Path(folder)/'work')
            expected = engine.proof_id_for(str(evidence), 'work', 'release', 'executed', 'rec')
            with mock.patch.object(engine, 'read_ndjson', return_value=[{'work_id':'work','project_name':'project'}]), \
                 mock.patch.object(engine, '_approval_helper_command', return_value='COMMAND') as command:
                result = engine.run_approval_issue(args, paths)
            self.assertEqual(result.get('authority_command'), 'COMMAND')
            self.assertIn(expected, command.call_args.args[1])

    def test_production_authority_rejects_cached_sudo_mutation(self):
        import importlib.machinery
        path = REPO / 'security/pathway-approval'
        loader = importlib.machinery.SourceFileLoader('security_helper', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        helper = importlib.util.module_from_spec(spec)
        if os.environ.get('SECURITY_TEST_BASELINE'):
            original = subprocess.check_output(['git', '-C', str(REPO), 'show', 'HEAD:security/pathway-approval'])
            exec(compile(original, str(path), 'exec'), helper.__dict__)
        else:
            loader.exec_module(helper)
        with mock.patch.object(helper, '_validate_runtime'), \
             mock.patch.object(helper, '_command_invalidate') as mutate:
            with self.assertRaises(helper.AuthorityError) as caught:
                helper._dispatch(['invalidate', '--ticket-id', 'AT-123456789abc',
                                  '--reason', 'test'], helper.PRODUCTION_CONFIG, None)
            self.assertEqual(caught.exception.code, 'fresh-authentication-unavailable')
            mutate.assert_not_called()

    def test_focused_verifier_rejects_production_scope_before_drill(self):
        path = REPO / '.planning/per-project-observability-contracts/observability/verify_agents_runtime_receipt.py'
        with tempfile.TemporaryDirectory() as folder:
            if os.environ.get('SECURITY_TEST_BASELINE'):
                original = subprocess.check_output(['git', '-C', str(REPO), 'show',
                    'HEAD:.planning/per-project-observability-contracts/observability/verify_agents_runtime_receipt.py'])
                path = Path(folder) / 'old_verifier.py'
                path.write_bytes(original)
            receipt = Path(folder) / 'receipt.json'
            for scope, environment in [('production', 'production'), ('runtime', 'production')]:
                receipt.write_text(json.dumps({'observability_receipt': {
                    'claim_scope': scope, 'environment_class': environment}}))
                result = subprocess.run([sys.executable, str(path), str(receipt)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('focused drill requires', result.stdout + result.stderr)

    def test_installer_rejects_symlink_ancestor_before_copy(self):
        source = (REPO / 'scripts/install-pathway-approval-authority.sh').read_text()
        if os.environ.get('SECURITY_TEST_BASELINE'):
            source = subprocess.check_output(['git', '-C', str(REPO), 'show',
                'HEAD:scripts/install-pathway-approval-authority.sh'], text=True)
        self.assertIn('require_secure_dir()', source)
        start = source.index('require_secure_dir()')
        end = source.index('\nfor path in / /private', start)
        self.assertLess(end, source.index('"$STAGED_HELPER" "$INSTALL_HELPER"'))
        function = source[start:end]
        with tempfile.TemporaryDirectory() as folder:
            link = Path(folder) / 'libexec'
            link.symlink_to('/usr', target_is_directory=True)
            script = 'fail() { echo "$*"; exit 2; }\n' + function + '\nrequire_secure_dir "$1"\n'
            result = subprocess.run(['/bin/sh', '-c', script, 'test', str(link)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('unsafe destination', result.stdout)

if __name__ == '__main__':
    unittest.main()
