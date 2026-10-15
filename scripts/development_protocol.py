"""Persistent ordered checklist. Complements, never replaces, pathway proof credit."""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

STEPS = [
    ("pathway", "/pathway"),
    ("brainstorm", "/brainstorm-stack --deep"),
    ("research", "/research-stack --deep"),
    ("karpathy-spec", "/karpathy spec"),
    ("planning", "/planning-stack --deep"),
    ("visual-spec", "Visual Spec Pack + spec_pack_check.py"),
    ("design", "/design-stack"),
    ("premortem", "/devilsadvocate --premortem"),
    ("audit-setup", "/audit-setup --all"),
    ("build", "/build-stack --review"),
    ("karpathy-verify", "/karpathy verify"),
    ("review", "/review-stack --audit"),
    ("simplify", "/simplify"),
    ("commit", "/commit"),
    ("ship", "/ship"),
    ("compound", "/compound"),
    ("closeout", "/closeout-stack"),
]
TERMINAL = {"passed", "not-applicable"}


def now():
    return datetime.now(ZoneInfo("America/Chicago")).isoformat()


def digest(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("invalid protocol store")
    for record in data:
        if not isinstance(record, dict) or [s["step_id"] for s in record["steps"]] != [
            s[0] for s in STEPS
        ]:
            raise ValueError("invalid protocol checklist")
    return data


def write(path, records):
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(records, stream, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def start(path, work_id, project, goal, required=()):
    with locked(path):
        records = read(path)
        existing = next((r for r in records if r["work_id"] == work_id), None)
        if existing:
            if existing["project"] != str(project) or existing["goal"] != goal:
                raise ValueError(
                    "work identity changed; reuse the original project and goal"
                )
            return existing
        trivial = bool(
            re.search(r"\b(typo|copy edit|one-line|trivial|tiny fix)\b", goal, re.I)
        )
        ui = bool(
            re.search(
                r"\b(ui|ux|screen|page|frontend|dashboard|visual|design)\b", goal, re.I
            )
        )
        research = bool(
            re.search(
                r"\b(research|unknown|investigate|evaluate|compare|regulation)\b",
                goal,
                re.I,
            )
        )
        conditional = {"research", "visual-spec", "design", "brainstorm"}
        if trivial:
            conditional |= {
                "karpathy-spec",
                "planning",
                "premortem",
                "audit-setup",
                "karpathy-verify",
                "simplify",
                "compound",
            }
        mandatory = set(required)
        if ui:
            mandatory |= {"visual-spec", "design"}
        if research:
            mandatory.add("research")
        if not trivial:
            mandatory.add("brainstorm")
        record = dict(
            work_id=work_id, project=str(project), goal=goal, created_at=now(), steps=[]
        )
        for i, (sid, command) in enumerate(STEPS):
            record["steps"].append(
                dict(
                    step_id=sid,
                    sequence=i + 1,
                    skill=command,
                    command=command,
                    required=sid not in conditional or sid in mandatory,
                    status="pending",
                    evidence_path="",
                    verify_command="",
                    verified_at="",
                    exception_reason="",
                    dependencies={},
                    evidence_sha256="",
                    verifier_exit=None,
                )
            )
        write(path, records + [record])
        return record


def refresh(record):
    """Read-time invalidation: altered evidence or instrument reopens descendants."""
    invalid = False
    for step in record["steps"]:
        if step["status"] == "passed":
            changed = digest(step["evidence_path"]) != step["evidence_sha256"]
            changed |= any(digest(p) != sha for p, sha in step["dependencies"].items())
            if changed or invalid:
                step["status"] = "pending"
                step["exception_reason"] = (
                    "Evidence or instrument changed; repeat this step."
                )
                invalid = True
    return record


def summary(record, work_id):
    if record is None:
        return dict(work_id=work_id, exists=False, ready=False, open=[], steps=[])
    record = refresh(record)
    open_steps = [s["step_id"] for s in record["steps"] if s["status"] not in TERMINAL]
    for row in record["steps"]:
        row["next_step"] = open_steps[0] if open_steps else None
    return dict(
        work_id=work_id,
        exists=True,
        ready=not open_steps,
        open=open_steps,
        next_step=open_steps[0] if open_steps else None,
        steps=record["steps"],
    )


def status(path, work_id):
    with locked(path):
        records = read(path)
        record = next((r for r in records if r["work_id"] == work_id), None)
        before = json.dumps(record, sort_keys=True) if record is not None else ""
        result = summary(record, work_id)
        after = json.dumps(record, sort_keys=True) if record is not None else ""
        if record is not None and before != after:
            write(path, records)
        return result


def step(
    path,
    work_id,
    step_id,
    result,
    evidence="",
    verify_cmd="",
    reason="",
    instruments=(),
):
    with locked(path):
        records = read(path)
        record = next((r for r in records if r["work_id"] == work_id), None)
        if record is None:
            raise ValueError("protocol work item does not exist")
        refresh(record)
        target = next((s for s in record["steps"] if s["step_id"] == step_id), None)
        if target is None:
            raise ValueError("unknown protocol step")
        if result == "na":
            if target["required"] or not reason.strip():
                raise ValueError("N/A requires a conditional step and a written reason")
            target.update(
                status="not-applicable",
                exception_reason=reason.strip(),
                verified_at=now(),
            )
        elif result in {"pass", "running", "blocked"}:
            if any(
                s["status"] not in TERMINAL
                for s in record["steps"][: target["sequence"] - 1]
            ):
                raise ValueError(
                    "earlier checklist rows remain open, including conditional rows"
                )
            if result != "pass":
                target.update(status=result, exception_reason=reason)
            else:
                p = Path(evidence).expanduser()
                if (
                    not p.is_absolute()
                    or p.is_symlink()
                    or not p.is_file()
                    or not verify_cmd.strip()
                ):
                    raise ValueError(
                        "pass requires absolute regular evidence file and verifier"
                    )
                dependencies = {}
                for name in instruments:
                    q = Path(name).expanduser()
                    if not q.is_absolute() or not q.is_file():
                        raise ValueError("instrument must be an existing absolute file")
                    dependencies[str(q)] = digest(q)
                sha = digest(p)
                if (
                    target["status"] == "passed"
                    and target["evidence_sha256"] == sha
                    and target["verify_command"] == verify_cmd
                    and target["dependencies"] == dependencies
                ):
                    return dict(ok=True, idempotent=True, **summary(record, work_id))
                try:
                    completed = subprocess.run(
                        verify_cmd,
                        shell=True,
                        cwd=record["project"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=60,
                    )
                    code = completed.returncode
                    output_hash = hashlib.sha256(completed.stdout).hexdigest()
                except subprocess.TimeoutExpired:
                    code, output_hash = 124, ""
                stable = sha == digest(p) and all(
                    digest(q) == h for q, h in dependencies.items()
                )
                target.update(
                    status="passed" if code == 0 and stable else "blocked",
                    evidence_path=str(p),
                    evidence_sha256=sha,
                    verify_command=verify_cmd,
                    dependencies=dependencies,
                    verifier_exit=code,
                    output_sha256=output_hash,
                    verified_at=now(),
                    exception_reason=""
                    if code == 0 and stable
                    else "Verifier failed, timed out, or inputs changed.",
                )
                if target["status"] == "blocked":
                    write(path, records)
                    return dict(
                        ok=False,
                        error=target["exception_reason"],
                        **summary(record, work_id),
                    )
        else:
            raise ValueError("result must be pass, na, running, or blocked")
        record["updated_at"] = now()
        write(path, records)
        return dict(ok=True, **summary(record, work_id))


def enforce_close(path, work_id):
    try:
        current = status(path, work_id)
        return (not current["exists"] or current["ready"]), current
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return False, dict(ready=False, open=["invalid-protocol-store"], error=str(exc))
