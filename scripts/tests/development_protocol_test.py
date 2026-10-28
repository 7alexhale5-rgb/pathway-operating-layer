#!/usr/bin/env python3
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import development_protocol as d


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        store = root / "protocol.json"
        evidence = root / "proof.txt"
        evidence.write_text("ok\n")
        rec = d.start(store, "W-test", "/tmp", "build a UI screen")
        ids = [s["step_id"] for s in rec["steps"]]
        assert ids == [x[0] for x in d.STEPS]
        assert rec["steps"][ids.index("visual-spec")]["required"]
        assert rec["steps"][ids.index("research")]["required"] is False
        assert d.step(
            store,
            "W-test",
            "research",
            "na",
            reason="No outside facts affect this work",
        )["ok"]
        try:
            d.step(store, "W-test", "karpathy-spec", "pass", str(evidence), "true")
        except ValueError:
            pass
        else:
            raise AssertionError("out of order pass accepted")
        assert d.step(store, "W-test", "pathway", "pass", str(evidence), "true")["ok"]
        assert d.step(store, "W-test", "brainstorm", "pass", str(evidence), "true")[
            "ok"
        ]
        assert d.step(store, "W-test", "karpathy-spec", "pass", str(evidence), "true")[
            "ok"
        ]
        assert d.step(store, "W-test", "karpathy-spec", "pass", str(evidence), "true")[
            "idempotent"
        ]
        failed = d.step(store, "W-test", "planning", "pass", str(evidence), "false")
        assert not failed["ok"]
        try:
            d.step(store, "W-test", "research", "na")
        except ValueError:
            pass
        else:
            raise AssertionError("N/A without reason accepted")
        evidence.write_text("changed\n")
        assert "karpathy-spec" in d.status(store, "W-test")["open"]
    print("development protocol tests: passed")



# Explicit lane and recovery regression fixtures. All stores are throwaway.
import unittest
import hashlib
import json
import copy
from unittest.mock import patch


class LaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "protocol.json"
        self.goal = "Normal feature with unchanged UI compatibility"
        self.work = {"work_id": "W-fixture", "project": str(self.root), "goal": self.goal, "status": "active"}
        self.evidence = self.root / "proof.txt"
        self.evidence.write_text("proof")

    def start(self, **kw):
        return d.start(self.store, self.work["work_id"], str(self.root), self.goal, **kw)

    def required(self, record):
        return {s["step_id"] for s in record["steps"] if s["required"]}

    def reject_unchanged(self, call):
        before = self.store.read_bytes() if self.store.exists() else None
        with self.assertRaises((ValueError, OSError)):
            call()
        self.assertEqual(before, self.store.read_bytes() if self.store.exists() else None)

    def scope(self, lane="normal", ui=False, extras=(), **updates):
        plan = self.root / "approved-plan.md"
        if not plan.exists():
            plan.write_text("approved scope")
        body = {"work_id": self.work["work_id"], "project": str(self.root),
                "goal_sha256": hashlib.sha256(self.goal.encode()).hexdigest(),
                "lane": lane, "ui": ui, "extra_required": list(extras), "reason": "reviewed scope",
                "approved_plan": {"path": str(plan), "sha256": d.digest(plan)}}
        body.update(updates)
        review = self.root / "scope-review.json"
        review.write_text(json.dumps({"verdict": "APPROVE", "reviewer": "independent-fixture",
                                     "contract_sha256": d.object_digest(body)}))
        body["review"] = {"path": str(review), "sha256": d.digest(review)}
        scope = self.root / "scope.json"
        scope.write_text(json.dumps(body))
        return scope

    def classify(self, scope, lane="normal", ui=False, **kw):
        return d.classify(self.store, self.work, lane, ui, str(scope), "reviewed lane",
                          kw.pop("expected", d.record_digest(d.refresh(copy.deepcopy(d.read(self.store)[0])))), **kw)

    def test_exact_matrix(self):
        small = {"pathway", "build", "karpathy-verify", "commit", "ship"}
        normal = small | {"karpathy-spec", "planning", "review", "closeout"}
        for lane, ui, expected in [("small", False, small), ("small", True, small | {"visual-spec", "design"}),
                                   ("normal", False, normal), ("normal", True, normal | {"visual-spec", "design"}),
                                   ("irreversible", False, {x[0] for x in d.STEPS})]:
            with self.subTest(lane=lane, ui=ui):
                store = self.root / (lane + str(ui) + ".json")
                r = d.start(store, "W", str(self.root), self.goal, lane=lane, ui=ui)
                self.assertEqual(expected, self.required(r))
                self.assertEqual([x[0] for x in d.STEPS], [x["step_id"] for x in r["steps"]])

    def test_goal_independence_and_legacy_compatibility(self):
        for i, goal in enumerate(["unchanged UI compatibility", "backend page receipt", "add helper"]):
            record = d.start(self.root / f"explicit-{i}.json", "W", str(self.root), goal, (), lane="normal", ui=False)
            self.assertEqual(d.NORMAL, self.required(record))
        record = d.start(self.root / "irreversible.json", "W", str(self.root), "one-line typo", (), lane="irreversible", ui=False)
        self.assertEqual({sid for sid, _ in d.STEPS}, self.required(record))
        for i, (goal, count) in enumerate([("one-line typo", 6), ("ordinary feature", 14),
                                           ("build screen", 16), ("research provider", 15)]):
            record = d.start(self.root / f"legacy-{i}.json", "W", str(self.root), goal, ())
            self.assertEqual(count, len(self.required(record)))
            self.assertEqual("legacy-inferred", record["scope_source"])

    def test_legacy_classifier_and_explicit_extras(self):
        r = self.start(required=("planning", "research"))
        self.assertEqual(["planning", "research"], r["extra_required"])
        self.assertTrue({"brainstorm", "visual-spec", "design"} <= self.required(r))
        self.assertEqual(r, self.start())
        self.assertEqual(r, self.start(required=("research", "planning")))
        self.reject_unchanged(lambda: self.start(required=()))
        self.reject_unchanged(lambda: self.start(required=("planning", "research", "compound")))

    def test_invalid_inputs_and_repeat_scope(self):
        for kw in [{"lane": "normal"}, {"ui": False}, {"lane": "fake", "ui": False},
                   {"lane": "normal", "ui": "no"}, {"required": ("unknown",)}]:
            self.reject_unchanged(lambda kw=kw: self.start(**kw))
        r = self.start(lane="normal", ui=False)
        self.assertEqual(r, self.start())
        self.assertEqual(r, self.start(lane="normal", ui=False))
        self.reject_unchanged(lambda: self.start(lane="small", ui=False))

    def test_ambiguous_legacy_preserves_all_required(self):
        r = self.start(required=("planning",))
        # Simulate old persisted format, not a live ledger edit.
        r.pop("extra_required")
        r.pop("scope_source", None)
        d.write(self.store, [r])
        expected = self.required(r)
        out = self.classify(self.scope())
        self.assertTrue(expected <= self.required(out["record"]))
        self.assertEqual(expected, set(out["record"]["legacy_protected_required"]))
        self.assertFalse(out["ready"])
        self.assertEqual(r["steps"], out["record"]["history"][0]["before"]["steps"])

    def test_evidence_identity_and_replacement_never_restore_passes(self):
        self.start(lane="normal", ui=False)
        scope = self.scope()
        a = self.classify(scope)
        self.assertTrue(self.classify(scope)["idempotent"])
        d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        plan = self.root / "approved-plan.md"
        plan.write_text("changed scope evidence")
        status = d.status(self.store, self.work["work_id"])
        self.assertFalse(status["ready"])
        self.assertEqual("pending", status["steps"][0]["status"])
        self.reject_unchanged(lambda: self.classify(scope))
        scope = self.scope()  # fresh independently reviewed fixture evidence
        b = self.classify(scope)
        self.assertFalse(b.get("idempotent", False))
        self.assertEqual("pending", b["steps"][0]["status"])
        self.assertGreater(len(b["record"]["history"]), len(a["record"]["history"]))

    def test_replacement_path_and_symlink_invalidate_scope(self):
        self.start(lane="normal", ui=False)
        scope = self.scope()
        self.classify(scope)
        d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        # A new valid reviewed document at a different path is a new evidence identity.
        replacement = self.root / "replacement.json"
        replacement.write_bytes(scope.read_bytes())
        result = self.classify(replacement)
        self.assertEqual("pending", result["steps"][0]["status"])
        d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        plan = self.root / "approved-plan.md"
        target = self.root / "identical-plan.md"
        target.write_bytes(plan.read_bytes())
        plan.unlink(); plan.symlink_to(target)
        result = d.status(self.store, self.work["work_id"])
        self.assertTrue(result["scope_invalid"])
        self.assertEqual("pending", result["steps"][0]["status"])

    def test_verifier_timeout_mutation_and_evidence_guards(self):
        self.start(lane="small", ui=False)
        link = self.root / "proof-link"; link.symlink_to(self.evidence)
        for evidence in [self.root / "missing", link, Path("relative.txt")]:
            self.reject_unchanged(lambda evidence=evidence: d.step(self.store, self.work["work_id"],
                "pathway", "pass", str(evidence), "true"))
        with patch.object(d.subprocess, "run", side_effect=d.subprocess.TimeoutExpired("true", 60)):
            result = d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        self.assertFalse(result["ok"])
        self.assertEqual(124, result["steps"][0]["verifier_exit"])
        def mutate(*args, **kwargs):
            self.evidence.write_text("mutated during verification")
            return d.subprocess.CompletedProcess("true", 0, b"ok")
        with patch.object(d.subprocess, "run", side_effect=mutate):
            result = d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        self.assertFalse(result["ok"])
        for status in ["running", "blocked"]:
            d.step(self.store, self.work["work_id"], "pathway", status)
            self.reject_unchanged(lambda: d.step(self.store, self.work["work_id"], "build", "pass", str(self.evidence), "true"))

    def test_downward_scope_extra_loss_and_closed_rejected(self):
        self.start(lane="normal", ui=True, required=("research",))
        self.reject_unchanged(lambda: self.classify(self.scope("small", True, ("research",)), "small", True))
        self.reject_unchanged(lambda: self.classify(self.scope("normal", False, ("research",)), "normal", False))
        self.reject_unchanged(lambda: self.classify(self.scope("normal", True), "normal", True))
        self.work["status"] = "closed"
        self.reject_unchanged(lambda: self.classify(self.scope("normal", True, ("research",)), "normal", True))

    def test_stale_digest_bad_identity_and_symlink(self):
        self.start(lane="normal", ui=False)
        scope = self.scope()
        self.reject_unchanged(lambda: self.classify(scope, expected="wrong"))
        self.reject_unchanged(lambda: self.classify(self.scope(work_id="another")))
        scope = self.scope()
        link = self.root / "link.json"
        link.symlink_to(scope)
        self.reject_unchanged(lambda: self.classify(link))

    def test_newly_required_na_reopens_descendants_and_preserves_history(self):
        self.start(lane="small", ui=False)
        for sid, _ in d.STEPS:
            rec = d.status(self.store, self.work["work_id"])
            row = next(s for s in rec["steps"] if s["step_id"] == sid)
            d.step(self.store, self.work["work_id"], sid, "pass" if row["required"] else "na",
                   str(self.evidence), "true", reason="lane: small")
        self.assertTrue(d.enforce_close(self.store, self.work["work_id"])[0])
        result = self.classify(self.scope("normal", False))
        self.assertFalse(result["ready"])
        rows = {s["step_id"]: s for s in result["steps"]}
        self.assertEqual("pending", rows["karpathy-spec"]["status"])
        self.assertEqual("pending", rows["build"]["status"])
        self.assertTrue(result["record"]["history"])

    def test_frozen_historical_api_receipt_and_unproved_reconstruction(self):
        record = self.start(required=("planning", "research"))
        record.pop("extra_required")
        d.write(self.store, [record])
        module = self.root / "historical-module.py"; module.write_text("fixture historical source")
        execution = self.root / "frozen-execution.json"
        raw = {"kind": "completed-protocol-start", "caller": "api", "required": ["planning", "research"],
               "result": {"ok": True, "protocol": record}, "execution_id": "original-fixture-execution",
               "executed_source_versions": {"module_sha256": "edf83750d79ac87895b94e3bf816ff216e16475151490628a359416aa459eafb"}}
        execution.write_text(json.dumps({"records": [raw]}))
        version = "edf83750d79ac87895b94e3bf816ff216e16475151490628a359416aa459eafb"
        provenance = {k: record[k] for k in ("work_id", "project", "goal", "created_at")}
        provenance.update(execution_id="original-fixture-execution", source_module={"path": str(module), "sha256": version},
                          execution={"path": str(execution), "sha256": d.digest(execution)}, locator=["records", 0])
        proof = self.root / "provenance.json"; review = self.root / "provenance-review.json"
        def save_provenance():
            review.write_text(json.dumps({"verdict": "APPROVE", "reviewer": "independent-fixture",
                                          "contract_sha256": d.object_digest(provenance)}))
            proof.write_text(json.dumps(dict(provenance, review={"path": str(review), "sha256": d.digest(review)})))
            return {"path": str(proof), "sha256": d.digest(proof)}
        ref = save_provenance()
        # Real hash mismatches are refused. Mock ONLY recognized source bytes for this structural fixture.
        self.reject_unchanged(lambda: self.classify(self.scope(extras=("planning", "research"), provenance=ref)))
        real_digest = d.digest
        with patch.object(d, "digest", side_effect=lambda p: version if Path(p) == module else real_digest(p)):
            result = self.classify(self.scope(extras=("planning", "research"), provenance=ref))
        self.assertFalse(result["record"]["legacy_extras_unknown"])
        self.assertEqual(["planning", "research"], result["record"]["extra_required"])
        self.assertEqual(d.NORMAL | {"research"}, self.required(result["record"]))
        # Replay variants against the original legacy record. No proposed command or assurance substitutes.
        for change in [{"required": None}, {"result": {"ok": False}}, {"kind": "proposed-command"},
                       {"caller": "unknown"}, {"required": ["unknown"]},
                       {"executed_source_versions": None}, {"executed_source_versions": {"module_sha256": "unrelated"}},
                       {"execution_id": "unrelated-execution"}, {"execution_id": ""}]:
            d.write(self.store, [record])
            execution.write_text(json.dumps({"records": [dict(raw, **change)]}))
            provenance["execution"]["sha256"] = real_digest(execution)
            ref = save_provenance()
            with patch.object(d, "digest", side_effect=lambda p: version if Path(p) == module else real_digest(p)):
                self.reject_unchanged(lambda: self.classify(self.scope(extras=("planning", "research"), provenance=ref)))

    def test_frozen_cli_source_version_binding(self):
        record = self.start(); record.pop("extra_required"); d.write(self.store, [record])
        module = self.root / "original-module.py"; module.write_text("synthetic fixture module")
        cli = self.root / "original-cli.py"; cli.write_text("development_protocol.start(path, wid, project, goal)")
        module_sha = "edf83750d79ac87895b94e3bf816ff216e16475151490628a359416aa459eafb"
        cli_sha = "022cb2a001fc5f0f5400901eb96937afe419f9f86de99dcafab582070b1ca9ed"
        execution = self.root / "original-execution.json"
        raw = {"kind": "completed-protocol-start", "caller": "cli", "execution_id": "fixture-original",
            "executed_source_versions": {"module_sha256": module_sha, "cli_sha256": cli_sha},
            "argv": ["python3", str(cli), "protocol-start", "--work-id", record["work_id"],
                     "--project", record["project"], "--goal", record["goal"], "--json"],
            "result": {"ok": True, "protocol": record}}
        provenance = {k: record[k] for k in ("work_id", "project", "goal", "created_at")}
        provenance.update(execution_id="fixture-original", source_module={"path": str(module), "sha256": module_sha},
            source_cli={"path": str(cli), "sha256": cli_sha}, locator=["records", 0])
        proof = self.root / "cli-provenance.json"; review = self.root / "cli-provenance-review.json"
        real_digest = d.digest
        # Synthetic source hashes isolate the binding parser; this never proves historical S9 code.
        def fixture_digest(path):
            return module_sha if Path(path) == module else cli_sha if Path(path) == cli else real_digest(path)
        for versions in [raw["executed_source_versions"], {"module_sha256": module_sha},
                         {"module_sha256": module_sha, "cli_sha256": "unrelated"}]:
            d.write(self.store, [record])
            execution.write_text(json.dumps({"records": [dict(raw, executed_source_versions=versions)]}))
            provenance["execution"] = {"path": str(execution), "sha256": real_digest(execution)}
            review.write_text(json.dumps({"verdict": "APPROVE", "reviewer": "independent fixture",
                "contract_sha256": d.object_digest(provenance)}))
            proof.write_text(json.dumps(dict(provenance, review={"path": str(review), "sha256": real_digest(review)})))
            ref = {"path": str(proof), "sha256": real_digest(proof)}
            with patch.object(d, "digest", side_effect=fixture_digest):
                if versions == raw["executed_source_versions"]:
                    result = self.classify(self.scope(provenance=ref))
                    self.assertEqual(d.NORMAL, self.required(result["record"]))
                else:
                    self.reject_unchanged(lambda: self.classify(self.scope(provenance=ref)))

    def test_scope_missing_review_bad_binding_and_stale_writer(self):
        self.start(lane="normal", ui=False)
        old = d.status(self.store, self.work["work_id"])["record_sha256"]
        result = self.classify(self.scope())
        self.reject_unchanged(lambda: self.classify(self.scope(), expected=old))
        self.assertTrue(result["record"]["history"])
        for changes in [{"goal_sha256": "wrong"}, {"project": "/foreign"}, {"reason": ""},
                        {"extra_required": ["unknown"]}, {"approved_plan": {"path": "relative", "sha256": "bad"}}]:
            self.reject_unchanged(lambda changes=changes: self.classify(self.scope(**changes)))
        scope = self.scope()
        (self.root / "scope-review.json").write_text('{}')
        self.reject_unchanged(lambda: self.classify(scope))

    def test_existing_proof_guards_and_atomic_io_failure(self):
        self.start(lane="small", ui=False)
        self.reject_unchanged(lambda: d.step(self.store, self.work["work_id"], "build", "na", reason="bypass"))
        self.reject_unchanged(lambda: d.step(self.store, self.work["work_id"], "research", "na"))
        self.reject_unchanged(lambda: d.step(self.store, self.work["work_id"], "build", "pass", str(self.evidence), "true"))
        result = d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "false")
        self.assertFalse(result["ok"])
        inst = self.root / "instrument.py"; inst.write_text("first")
        d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true", instruments=(str(inst),))
        inst.write_text("changed")
        self.assertFalse(d.enforce_close(self.store, self.work["work_id"])[0])
        scope = self.scope("small", False)
        before = self.store.read_bytes()
        with patch.object(d.os, "replace", side_effect=OSError("fixture disk error")):
            with self.assertRaises(OSError): self.classify(scope, "small", False)
        self.assertEqual(before, self.store.read_bytes())


if __name__ == "__main__":
    main()
    unittest.main()
