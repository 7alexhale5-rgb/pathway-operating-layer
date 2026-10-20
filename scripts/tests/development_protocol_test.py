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


if __name__ == "__main__":
    main()
