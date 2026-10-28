#!/usr/bin/env python3
import json
import os
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
        missing_project = root / "removed-project"
        missing_project.mkdir()
        d.start(store, "W-missing", str(missing_project), "verify a missing project")
        missing_project.rmdir()
        failed = d.step(store, "W-missing", "pathway", "pass", str(evidence), "true")
        assert not failed["ok"]
        record = next(row for row in json.loads(store.read_text()) if row["work_id"] == "W-missing")
        blocked = next(row for row in record["steps"] if row["step_id"] == "pathway")
        assert blocked["status"] == "blocked"
        assert blocked["verifier_exit"] == 127
        assert blocked["output_sha256"] == ""
        alias = root / "project-link"
        alias.symlink_to(root, target_is_directory=True)
        for index, legacy in enumerate((str(root) + "/", str(alias))):
            wid = "W-legacy-" + str(index)
            d.start(store, wid, legacy, "legacy goal")
            expected = (str(root.resolve()), "legacy goal")
            d.status(store, wid, expected)
            assert next(r for r in d.read(store) if r["work_id"] == wid)["project"] == expected[0]
            assert d.start(store, wid, expected[0], expected[1])["project"] == expected[0]
            for wrong in ((str(root.parent), "legacy goal"), (expected[0], "changed goal")):
                try:
                    d.status(store, wid, wrong)
                except ValueError:
                    pass
                else:
                    raise AssertionError("changed legacy identity accepted")
        d.start(store, "W-legacy-start", str(alias), "legacy goal")
        assert d.start(store, "W-legacy-start", str(root.resolve()), "legacy goal")["project"] == str(root.resolve())
        original_cwd = Path.cwd()
        try:
            os.chdir(root)
            d.start(store, "W-relative", ".", "legacy goal")
            d.status(store, "W-relative", (str(root.resolve()), "legacy goal"))
            assert d.start(store, "W-relative", str(root.resolve()), "legacy goal")["project"] == str(root.resolve())
            assert next(r for r in d.read(store) if r["work_id"] == "W-relative")["project"] == str(root.resolve())
        finally:
            os.chdir(original_cwd)
        first = root / "project-a"
        second = root / "project-b"
        first.mkdir()
        second.mkdir()
        d.start(store, "W-relative-legacy", str(first), "same goal")
        rows = d.read(store)
        legacy = next(r for r in rows if r["work_id"] == "W-relative-legacy")
        legacy["project"] = "."  # Actual pre-canonicalization persisted shape.
        for row in legacy["steps"]:
            row["status"] = "not-applicable"
        d.write(store, rows)
        try:
            os.chdir(second)
            migrated = d.status(store, "W-relative-legacy", (str(second.resolve()), "same goal"))
            assert not migrated["ready"]
            saved = next(r for r in d.read(store) if r["work_id"] == "W-relative-legacy")
            assert all(row["status"] == "pending" for row in saved["steps"])
        finally:
            os.chdir(original_cwd)
        for transition in ("running", "blocked", "pass"):
            wid = "W-reopen-" + transition
            proof = root / (wid + ".txt")
            proof.write_text("v1")
            d.start(store, wid, str(root), "build a UI screen")
            for sid, _ in d.STEPS:
                step_proof = proof if sid == "build" else root / (wid + "-" + sid + ".txt")
                step_proof.write_text("v1")
                assert d.step(store, wid, sid, "pass", str(step_proof), "true")["ok"]
            assert d.status(store, wid)["ready"]
            if transition == "pass":
                # A changed verifier must revoke later completion even with identical bytes.
                d.step(store, wid, "build", "pass", str(proof), "test -f " + str(proof))
            else:
                d.step(store, wid, "build", transition)
                saved = next(r for r in d.read(store) if r["work_id"] == wid)
                assert next(s for s in saved["steps"] if s["step_id"] == "closeout")["status"] == "pending"
                proof.write_text("v2")
                assert d.step(store, wid, "build", "pass", str(proof), "true")["ok"]
                saved = next(r for r in d.read(store) if r["work_id"] == wid)
                assert next(s for s in saved["steps"] if s["step_id"] == "review")["status"] == "pending"
            assert not d.status(store, wid)["ready"]
            assert "review" in d.status(store, wid)["open"]
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

    def test_supplied_provenance_never_clears_legacy_rows(self):
        record = self.start(required=("planning", "research"))
        record.pop("extra_required")
        d.write(self.store, [record])
        receipt = self.root / "provenance.json"; receipt.write_text(json.dumps({"required": []}))
        ref = {"path": str(receipt), "sha256": d.digest(receipt)}
        self.reject_unchanged(lambda: self.classify(self.scope(extras=("planning", "research"), provenance=ref)))
        result = self.classify(self.scope(extras=("planning", "research")))
        self.assertTrue(result["record"]["legacy_extras_unknown"])
        self.assertTrue({s["step_id"] for s in record["steps"] if s["required"]} <= self.required(result["record"]))

    def test_history_entries_do_not_nest_earlier_history(self):
        self.start(lane="small", ui=False)
        for lane in ("normal", "irreversible"):
            self.classify(self.scope(lane, False), lane)
        for n in range(3):
            (self.root / "approved-plan.md").write_text(f"changed scope {n}")
            d.status(self.store, self.work["work_id"])
            self.root.joinpath("approved-plan.md").write_text("approved scope")
            self.classify(self.scope("irreversible", False), "irreversible")
        history = d.read(self.store)[0]["history"]
        self.assertGreaterEqual(len(history), 5)
        self.assertTrue(all("history" not in entry["before"] for entry in history))

    def test_scope_invalidation_preserves_na_reason_once(self):
        self.start(lane="normal", ui=False)
        self.classify(self.scope())
        d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence), "true")
        reason = "No research: the exact local module contract is already verified."
        d.step(self.store, self.work["work_id"], "research", "na", reason=reason)
        before = d.snapshot(d.read(self.store)[0])
        prior_row = next(row for row in before["steps"] if row["step_id"] == "research")
        (self.root / "approved-plan.md").write_text("changed scope")
        first = d.status(self.store, self.work["work_id"])
        saved = d.read(self.store)[0]
        events = [e for e in saved["history"] if e.get("kind") == "scope-evidence-invalidated"]
        self.assertEqual(1, len(events))
        self.assertEqual(before, events[0]["before"])
        self.assertEqual(d.object_digest(before), events[0]["before_sha256"])
        old_row = next(row for row in events[0]["before"]["steps"] if row["step_id"] == "research")
        self.assertEqual(reason, old_row["exception_reason"])
        self.assertEqual(prior_row["verified_at"], old_row["verified_at"])
        bytes_before_second = self.store.read_bytes()
        second = d.status(self.store, self.work["work_id"])
        self.assertEqual(bytes_before_second, self.store.read_bytes())
        self.assertEqual(first["record_sha256"], second["record_sha256"])
        self.classify(self.scope())
        (self.root / "approved-plan.md").write_text("changed again")
        d.status(self.store, self.work["work_id"])
        self.assertEqual(2, len([e for e in d.read(self.store)[0]["history"] if e.get("kind") == "scope-evidence-invalidated"]))

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
        # The module's own runner uses no shell: `||` is an argument to `false`, so this still fails.
        marker = self.root / "shell-ran"
        result = d.step(self.store, self.work["work_id"], "pathway", "pass", str(self.evidence),
                        f"false || touch {marker}")
        self.assertFalse(result["ok"])
        self.assertFalse(marker.exists())
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
