#!/usr/bin/env python3
"""Safe tests for the OS-separated Pathway approval authority.

The installed paths are never touched.  Tests import the standalone helper and
pass its private temp-only RuntimeConfig directly.
"""

import ast
import datetime
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import pwd
import shutil
import stat
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "security" / "pathway-approval"
INSTALLER = REPO / "scripts" / "install-pathway-approval-authority.sh"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("pathway_approval_authority", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


authority = load_helper()


def canonical(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


class AuthorityFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pathway-approval-test-")
        self.root = Path(self.temporary.name)
        self.config = authority._test_config(self.root)
        self.identity = authority.Identity(pwd.getpwuid(os.getuid()).pw_name, os.getuid())
        for directory in (
            self.root / "usr",
            self.root / "usr" / "local",
            self.root / "usr" / "local" / "libexec",
            self.root / "Library",
            self.root / "Library" / "Application Support",
            self.config.authority_dir,
        ):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o755)
        shutil.copyfile(HELPER, self.config.installed_path)
        self.config.installed_path.chmod(0o755)
        self.config.authority_ledger.write_bytes(b"")
        self.config.authority_ledger.chmod(0o644)

    def tearDown(self):
        self.temporary.cleanup()

    def dispatch(self, *args):
        return authority._dispatch(args, self.config, self.identity)

    def records(self):
        return authority._parse_ledger_bytes(self.config.authority_ledger.read_bytes())

    def release_subject(self, suffix="a"):
        return {
            "kind": authority.APPROVAL_KIND_RELEASE,
            "work_id": f"W-20260831-helper-release-{suffix * 6}",
            "project": "pathway-operating-layer",
            "stage": "production",
            "release_receipt_sha256": suffix * 64,
        }

    def waiver_subject(self, suffix="b", pathway="observability"):
        return {
            "kind": authority.APPROVAL_KIND_WAIVER,
            "schema_version": 2,
            "work_id": f"W-20260831-helper-waiver-{suffix * 6}",
            "project": "pathway-operating-layer",
            "pathway": pathway,
            "reason": f"{pathway} is deliberately waived in fixture {suffix}",
            "work_context_sha256": suffix * 64,
        }

    def issue(self, subject=None, consumer="P-0123456789ab"):
        subject = subject or self.release_subject()
        return self.dispatch(
            "issue",
            "--subject-json", json.dumps(subject),
            "--consumer", consumer,
            "--reason", subject.get("reason", "reviewed production receipt"),
        )

    def legacy_ticket(self, *, ticket_hex, subject, consumer, invalidated=False):
        issued_at = datetime.datetime(2026, 8, 31, 14, 0, tzinfo=datetime.timezone.utc)
        issued_text = issued_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_text = (issued_at + datetime.timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
        digest = authority._subject_digest(subject, allow_legacy=True)
        ticket_id = f"AT-{ticket_hex}"
        reason = subject.get("reason", "legacy reviewed production receipt")
        issued = {
            "event": "issued",
            "kind": subject["kind"],
            "subject_digest": digest,
            "ticket_id": ticket_id,
            "subject": subject,
            "issued_at": issued_text,
            "expires_at": expires_text,
            "reason": reason,
            "work_id": subject["work_id"],
            "issued_by": "uid=501 user=alexhale ppid=1 tty=/dev/ttys001",
        }
        consumed = {
            "event": "consumed",
            "kind": subject["kind"],
            "subject_digest": digest,
            "ticket_id": ticket_id,
            "at": issued_text,
            "work_id": subject["work_id"],
            "pathway": subject.get("pathway", ""),
            "consumed_by": consumer,
            "consumption_id": "AC-" + hashlib.sha256(
                f"{ticket_id}|{digest}|{consumer}".encode()
            ).hexdigest()[:12],
        }
        records = [issued, consumed]
        if invalidated:
            records.append({
                "event": "invalidated",
                "kind": subject["kind"],
                "subject_digest": digest,
                "ticket_id": ticket_id,
                "at": expires_text,
                "work_id": subject["work_id"],
                "reason": "legacy correction",
                "invalidated_by": "uid=501 user=alexhale ppid=1 tty=/dev/ttys001",
                "invalidation_id": "AI-" + ticket_hex,
            })
        return records

    def write_source(self, records, name="legacy.ndjson"):
        path = self.root / name
        payload = "".join(canonical(record) for record in records).encode()
        path.write_bytes(payload)
        path.chmod(0o600)
        return path, hashlib.sha256(payload).hexdigest()


class IssueAndVerifyTests(AuthorityFixture):
    def test_issue_atomically_appends_exact_issued_and_consumed_schemas(self):
        result = self.issue()
        records = self.records()
        self.assertEqual(result["status"], "issued_and_consumed")
        self.assertEqual([record["event"] for record in records], ["issued", "consumed"])
        self.assertEqual(frozenset(records[0]), authority.ISSUED_FIELDS)
        self.assertEqual(frozenset(records[1]), authority.CONSUMED_FIELDS)
        self.assertEqual(records[0]["ticket_id"], records[1]["ticket_id"])
        self.assertEqual(records[1]["consumed_by"], "P-0123456789ab")
        issued = authority._parse_timestamp(records[0]["issued_at"], "issued_at")
        expires = authority._parse_timestamp(records[0]["expires_at"], "expires_at")
        self.assertEqual((expires - issued).total_seconds(), 900)
        self.assertEqual(result["ledger_sha256"], hashlib.sha256(self.config.authority_ledger.read_bytes()).hexdigest())
        self.assertEqual(stat.S_IMODE(self.config.authority_ledger.stat().st_mode), 0o644)

    def test_canonical_subject_digest_ignores_key_order_but_rejects_extra_fields(self):
        subject = self.release_subject()
        reordered = dict(reversed(list(subject.items())))
        self.assertEqual(authority._subject_digest(subject), authority._subject_digest(reordered))
        modified = {**subject, "extra": True}
        with self.assertRaisesRegex(authority.AuthorityError, "fixed schema"):
            authority._subject_digest(modified)

    def test_waiver_reason_and_pathway_are_exact(self):
        subject = self.waiver_subject()
        result = self.issue(subject, "work-cover:" + subject["work_id"] + ":observability")
        self.assertEqual(result["status"], "issued_and_consumed")
        with self.assertRaisesRegex(authority.AuthorityError, "exactly match"):
            self.dispatch(
                "issue", "--subject-json", json.dumps(subject),
                "--consumer", "consumer", "--reason", "different reason",
            )
        bad_pathway = {**subject, "pathway": "made-up"}
        with self.assertRaisesRegex(authority.AuthorityError, "not canonical"):
            self.dispatch(
                "issue", "--subject-json", json.dumps(bad_pathway),
                "--consumer", "consumer", "--reason", bad_pathway["reason"],
            )

    def test_new_waiver_requires_v2_immutable_work_context(self):
        subject = self.waiver_subject("c")
        legacy = {
            key: value for key, value in subject.items()
            if key not in {"schema_version", "work_context_sha256"}
        }
        with self.assertRaisesRegex(authority.AuthorityError, "fixed v2 schema"):
            self.issue(legacy, "work-cover:legacy")
        wrong_version = {**subject, "schema_version": 1}
        with self.assertRaisesRegex(authority.AuthorityError, "integer 2"):
            self.issue(wrong_version, "work-cover:wrong-version")
        wrong_context = {**subject, "work_context_sha256": "not-a-digest"}
        with self.assertRaisesRegex(authority.AuthorityError, "64 lowercase hex"):
            self.issue(wrong_context, "work-cover:wrong-context")
        self.assertEqual(
            authority._subject_digest(legacy, allow_legacy=True),
            hashlib.sha256(canonical(legacy).strip().encode()).hexdigest(),
        )

    def test_unicode_controls_cannot_spoof_reviewed_subject_reason_or_consumer(self):
        subject = self.release_subject("d")
        cases = (
            ({**subject, "project": "pathway\u202eexe"}, "consumer", "reviewed"),
            (subject, "P-safe\u2066hidden", "reviewed"),
            (subject, "P-safe", "reviewed\u2028different line"),
        )
        for candidate, consumer, reason in cases:
            with self.subTest(candidate=candidate, consumer=consumer, reason=reason):
                with self.assertRaisesRegex(authority.AuthorityError, "unsafe Unicode"):
                    self.dispatch(
                        "issue", "--subject-json", json.dumps(candidate),
                        "--consumer", consumer, "--reason", reason,
                    )

    def test_strict_json_rejects_duplicate_keys_constants_and_non_object(self):
        for payload in (
            '{"kind":"release-production-approval","kind":"production-secure-waiver"}',
            '{"kind":NaN}',
            '[]',
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(authority.AuthorityError):
                    self.dispatch(
                        "issue", "--subject-json", payload,
                        "--consumer", "consumer", "--reason", "reason",
                    )

    def test_verify_filters_exact_ticket_or_digest(self):
        issued = self.issue()
        by_ticket = self.dispatch("verify", "--ticket-id", issued["ticket_id"])
        by_digest = self.dispatch("verify", "--subject-digest", issued["subject_digest"])
        self.assertEqual((by_ticket["issued"], by_ticket["consumed"]), (1, 1))
        self.assertEqual(by_digest["consumption_ids"], [issued["consumption_id"]])
        with self.assertRaisesRegex(authority.AuthorityError, "No authority record"):
            self.dispatch("verify", "--ticket-id", "AT-ffffffffffff")


class StrictLedgerTests(AuthorityFixture):
    def test_malformed_truncated_and_blank_ledgers_fail_closed(self):
        cases = {
            "malformed": b'{"event":}\n',
            "truncated": b'{"event":"issued"}',
            "blank": b"\n",
            "utf8": b"\xff\n",
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                self.config.authority_ledger.write_bytes(payload)
                with self.assertRaises(authority.AuthorityError):
                    self.dispatch("verify")

    def test_reordered_consumption_before_issue_fails_closed(self):
        records = self.legacy_ticket(
            ticket_hex="111111111111",
            subject=self.release_subject("c"),
            consumer="P-111111111111",
        )
        self.config.authority_ledger.write_text(
            canonical(records[1]) + canonical(records[0]), encoding="utf-8",
        )
        with self.assertRaisesRegex(authority.AuthorityError, "precedes its issue"):
            self.dispatch("verify")

    def test_duplicate_consumption_and_consumption_after_invalidation_fail(self):
        records = self.legacy_ticket(
            ticket_hex="222222222222",
            subject=self.release_subject("d"),
            consumer="P-222222222222",
            invalidated=True,
        )
        duplicate = records[:2] + [{**records[1], "consumption_id": "AC-333333333333"}]
        with self.assertRaisesRegex(authority.AuthorityError, "repeats a consumption"):
            authority._parse_ledger_bytes("".join(canonical(row) for row in duplicate).encode())
        after = [records[0], records[2], records[1]]
        with self.assertRaisesRegex(authority.AuthorityError, "consumes an invalidated"):
            authority._parse_ledger_bytes("".join(canonical(row) for row in after).encode())

    def test_invalidation_is_exact_and_idempotent(self):
        issued = self.issue()
        first = self.dispatch(
            "invalidate", "--ticket-id", issued["ticket_id"], "--reason", "compromised legacy issue",
        )
        before = self.config.authority_ledger.read_bytes()
        second = self.dispatch(
            "invalidate", "--ticket-id", issued["ticket_id"], "--reason", "repeat correction",
        )
        after = self.config.authority_ledger.read_bytes()
        self.assertEqual(first["status"], "invalidated")
        self.assertEqual(second["status"], "already_invalidated")
        self.assertEqual(before, after)
        self.assertEqual(sum(row["event"] == "invalidated" for row in self.records()), 1)

    def test_projected_size_cap_refuses_before_append(self):
        small = authority._test_config(self.root, max_ledger_bytes=100)
        before = self.config.authority_ledger.read_bytes()
        with self.assertRaisesRegex(authority.AuthorityError, "requested append"):
            authority._dispatch(
                (
                    "issue", "--subject-json", json.dumps(self.release_subject("e")),
                    "--consumer", "P-eeeeeeeeeeee", "--reason", "reviewed",
                ),
                small,
                self.identity,
            )
        self.assertEqual(before, self.config.authority_ledger.read_bytes())


class BootstrapTests(AuthorityFixture):
    def setUp(self):
        super().setUp()
        self.config.authority_ledger.unlink()

    def test_bootstrap_hash_pins_and_invalidates_every_legacy_issuance(self):
        accepted = self.legacy_ticket(
            ticket_hex="aaaaaaaaaaaa",
            subject=self.release_subject("a"),
            consumer="P-aaaaaaaaaaaa",
        )
        rejected_subject = self.waiver_subject("b")
        rejected_subject.pop("schema_version")
        rejected_subject.pop("work_context_sha256")
        rejected = self.legacy_ticket(
            ticket_hex="bbbbbbbbbbbb",
            subject=rejected_subject,
            consumer="work-cover:W-20260831-helper-waiver-bbbbbb:observability",
        )
        preserved_invalid = self.legacy_ticket(
            ticket_hex="cccccccccccc",
            subject=self.release_subject("c"),
            consumer="P-cccccccccccc",
            invalidated=True,
        )
        source, digest = self.write_source(accepted + rejected + preserved_invalid)
        result = self.dispatch(
            "bootstrap", "--source-ledger", str(source), "--expected-sha256", digest,
            "--invalidate-all-issued", "--reason", "legacy authority was not independently authenticated",
        )
        records = self.records()
        rejected_events = [row for row in records if row["ticket_id"] == "AT-bbbbbbbbbbbb"]
        accepted_events = [row for row in records if row["ticket_id"] == "AT-aaaaaaaaaaaa"]
        preserved_events = [row for row in records if row["ticket_id"] == "AT-cccccccccccc"]
        self.assertEqual(result["status"], "bootstrapped")
        self.assertEqual(result["source_records"], 7)
        self.assertEqual(
            [row["event"] for row in accepted_events],
            ["issued", "consumed", "invalidated"],
        )
        self.assertEqual(
            [row["event"] for row in rejected_events],
            ["issued", "consumed", "invalidated"],
        )
        consumed_tickets = {
            row["ticket_id"] for row in records if row["event"] == "consumed"
        }
        causal_invalidations = {
            row["ticket_id"] for row in records
            if row["event"] == "invalidated" and row["ticket_id"] in consumed_tickets
        }
        self.assertEqual(
            causal_invalidations,
            {"AT-aaaaaaaaaaaa", "AT-bbbbbbbbbbbb", "AT-cccccccccccc"},
        )
        self.assertEqual([row["event"] for row in preserved_events], ["issued", "consumed", "invalidated"])
        self.assertEqual(
            result["invalidated_legacy_tickets"],
            ["AT-aaaaaaaaaaaa", "AT-bbbbbbbbbbbb", "AT-cccccccccccc"],
        )
        again = self.dispatch(
            "bootstrap", "--source-ledger", str(source), "--expected-sha256", digest,
            "--invalidate-all-issued", "--reason", "legacy authority was not independently authenticated",
        )
        self.assertEqual(again["status"], "already_bootstrapped")
        later = self.issue(self.release_subject("d"), "P-dddddddddddd")
        after_issue = self.dispatch(
            "bootstrap", "--source-ledger", str(source), "--expected-sha256", digest,
            "--invalidate-all-issued", "--reason", "legacy authority was not independently authenticated",
        )
        self.assertEqual(after_issue["status"], "already_bootstrapped")
        self.assertIn(later["ticket_id"], {row["ticket_id"] for row in self.records()})

    def test_bootstrap_digest_mismatch_or_missing_invalidate_all_fails(self):
        records = self.legacy_ticket(
            ticket_hex="dddddddddddd",
            subject=self.release_subject("d"),
            consumer="P-dddddddddddd",
        )
        source, digest = self.write_source(records)
        cases = (
            ("0" * 64, ("--invalidate-all-issued", "--reason", "reject legacy"), "does not match"),
            (digest, ("--reason", "reject legacy"), "invalidate-all-issued"),
        )
        for expected, extra, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(authority.AuthorityError, message):
                    self.dispatch(
                        "bootstrap", "--source-ledger", str(source),
                        "--expected-sha256", expected, *extra,
                    )

    def test_bootstrap_rejects_malformed_truncated_and_reordered_source(self):
        valid = self.legacy_ticket(
            ticket_hex="eeeeeeeeeeee",
            subject=self.release_subject("e"),
            consumer="P-eeeeeeeeeeee",
        )
        payloads = (
            b'{"event":}\n',
            canonical(valid[0]).encode().rstrip(b"\n"),
            (canonical(valid[1]) + canonical(valid[0])).encode(),
        )
        for index, payload in enumerate(payloads):
            source = self.root / f"bad-{index}.ndjson"
            source.write_bytes(payload)
            source.chmod(0o600)
            digest = hashlib.sha256(payload).hexdigest()
            with self.subTest(index=index):
                with self.assertRaises(authority.AuthorityError):
                    self.dispatch(
                        "bootstrap", "--source-ledger", str(source),
                        "--expected-sha256", digest, "--invalidate-all-issued",
                        "--reason", "reject legacy",
                    )

    def test_bootstrap_rejects_source_symlink_and_writable_permissions(self):
        records = self.legacy_ticket(
            ticket_hex="ffffffffffff",
            subject=self.release_subject("f"),
            consumer="P-ffffffffffff",
        )
        source, digest = self.write_source(records)
        link = self.root / "legacy-link.ndjson"
        link.symlink_to(source)
        with self.assertRaisesRegex(authority.AuthorityError, "opened safely"):
            self.dispatch(
                "bootstrap", "--source-ledger", str(link), "--expected-sha256", digest,
                "--invalidate-all-issued", "--reason", "reject legacy",
            )
        source.chmod(0o622)
        with self.assertRaisesRegex(authority.AuthorityError, "cannot be group or other writable"):
            self.dispatch(
                "bootstrap", "--source-ledger", str(source), "--expected-sha256", digest,
                "--invalidate-all-issued", "--reason", "reject legacy",
            )


class RuntimeBoundaryTests(AuthorityFixture):
    def test_identity_requires_root_and_matching_real_sudo_user(self):
        with self.assertRaisesRegex(authority.AuthorityError, "through sudo"):
            authority._validated_identity(euid=501, environment={})
        with self.assertRaisesRegex(authority.AuthorityError, "real sudo caller"):
            authority._validated_identity(euid=0, environment={})
        valid = authority._validated_identity(
            euid=0,
            environment={"SUDO_USER": self.identity.user, "SUDO_UID": str(self.identity.uid)},
        )
        self.assertEqual((valid.user, valid.uid), (self.identity.user, self.identity.uid))
        with self.assertRaisesRegex(authority.AuthorityError, "do not identify the same"):
            authority._validated_identity(
                euid=0,
                environment={"SUDO_USER": "root", "SUDO_UID": str(self.identity.uid)},
            )

    def test_installed_file_directory_and_ledger_permissions_fail_closed(self):
        cases = (
            (self.config.installed_path, 0o775),
            (self.config.installed_path.parent, 0o777),
            (self.config.authority_dir, 0o777),
            (self.config.authority_ledger, 0o622),
        )
        for path, unsafe_mode in cases:
            original = stat.S_IMODE(path.stat().st_mode)
            with self.subTest(path=path):
                path.chmod(unsafe_mode)
                with self.assertRaisesRegex(authority.AuthorityError, "writable"):
                    self.dispatch("verify")
                path.chmod(original)

    def test_installed_and_authority_symlinks_fail_closed(self):
        real_helper = self.root / "real-helper"
        self.config.installed_path.rename(real_helper)
        self.config.installed_path.symlink_to(real_helper)
        with self.assertRaisesRegex(authority.AuthorityError, "symlinks"):
            self.dispatch("verify")
        self.config.installed_path.unlink()
        real_helper.rename(self.config.installed_path)
        real_ledger = self.root / "real-ledger"
        self.config.authority_ledger.rename(real_ledger)
        self.config.authority_ledger.symlink_to(real_ledger)
        with self.assertRaisesRegex(authority.AuthorityError, "symlinks"):
            self.dispatch("verify")

    def test_cli_exposes_only_four_commands_and_no_authority_path_override(self):
        parser = authority._build_parser()
        choices = next(
            action.choices for action in parser._actions if action.dest == "command"
        )
        self.assertEqual(set(choices), {"bootstrap", "issue", "invalidate", "verify"})
        with self.assertRaisesRegex(authority.AuthorityError, "cannot be overridden"):
            self.dispatch("verify", "--ledger", str(self.root / "other"))

    def test_helper_has_only_stdlib_static_imports_and_no_repo_execution(self):
        source = HELPER.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertEqual(imports, {
            "argparse", "datetime", "fcntl", "hashlib", "json", "os", "pwd",
            "re", "secrets", "stat", "sys", "unicodedata", "pathlib",
        })
        self.assertNotIn("subprocess", source)
        self.assertNotIn("importlib", source)
        self.assertNotIn("sys.path", source)
        self.assertNotIn("/Users/", source)
        self.assertNotIn("Projects/", source)
        self.assertNotIn("os.exec", source)

    def test_installer_requires_password_no_env_and_zero_timestamp_cache(self):
        source = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("PATH=/usr/bin:/bin:/usr/sbin:/sbin", source)
        self.assertIn("timestamp_timeout=0", source)
        self.assertIn("PASSWD: NOSETENV:", source)
        self.assertNotIn("NOPASSWD", source)
        self.assertNotIn(" SETENV:", source)
        self.assertIn("visudo -cf", source)
        self.assertIn(
            "/usr/bin/sudo -k; /usr/bin/sudo /usr/local/libexec/pathway-approval verify", source,
        )
        self.assertIn("NEVER run this mutable repository copy with sudo", source)
        self.assertIn("Steady-state OS", source)
        self.assertIn('STAGE_DIR="/private/var/root/pathway-approval-bootstrap"', source)
        self.assertNotIn('STAGE_DIR="/var/root/pathway-approval-bootstrap"', source)
        helper_digest = hashlib.sha256(HELPER.read_bytes()).hexdigest()
        self.assertIn(f'PINNED_HELPER_SHA256="{helper_digest}"', source)
        self.assertIn("--expected-installer-sha256", source)
        self.assertIn("--expected-helper-sha256", source)
        self.assertIn(
            'LEGACY_SHA256="37b067ab41a9775769fce89ba1371171642a274c6cb6614a0f369a7636ba2a99"',
            source,
        )
        self.assertIn("--invalidate-all-issued", source)
        self.assertNotIn("--reject-ticket", source)
        self.assertLess(
            source.index('"$INSTALL_HELPER" bootstrap'),
            source.index("SUDOERS_TEMP="),
        )
        for unsafe in ("$(dirname ", "$(id ", "$(mktemp ", "\ninstall ", "\nchmod ", "\n  rm "):
            self.assertNotIn(unsafe, source)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print(f"{result.testsRun}/{result.testsRun} pathway approval helper tests passed")
    raise SystemExit(0 if result.wasSuccessful() else 1)
