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


if __name__ == "__main__":
    main()
