"""Persistent ordered checklist. Complements, never replaces, pathway proof credit."""

import contextlib
import copy
import ast
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


POLICY_VERSION = "explicit-lanes-v1"
LANES = {"small": 0, "normal": 1, "irreversible": 2}
SMALL = {"pathway", "build", "karpathy-verify", "commit", "ship"}
NORMAL = SMALL | {"karpathy-spec", "planning", "review", "closeout"}


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scope_inputs(lane, ui, required=None):
    if (lane is None) != (ui is None) or (lane is not None and (lane not in LANES or type(ui) is not bool)):
        raise ValueError("explicit lane and boolean UI scope must be supplied together")
    extras = None if required is None else set(required)
    if extras is not None and not extras <= {sid for sid, _ in STEPS}:
        raise ValueError("unknown extra required row")
    return extras


def requirements(goal, lane, ui, extras):
    if lane is not None:
        needed = set(SMALL if lane == "small" else NORMAL if lane == "normal" else {s for s, _ in STEPS})
        return needed | ({"visual-spec", "design"} if ui else set()) | set(extras)
    # Historical implicit behavior is retained until explicit, reviewed classification.
    trivial = bool(re.search(r"\b(typo|copy edit|one-line|trivial|tiny fix)\b", goal, re.I))
    conditional = {"research", "visual-spec", "design", "brainstorm"}
    if trivial:
        conditional |= {"karpathy-spec", "planning", "premortem", "audit-setup", "karpathy-verify", "simplify", "compound"}
    mandatory = set(extras)
    if re.search(r"\b(ui|ux|screen|page|frontend|dashboard|visual|design)\b", goal, re.I):
        mandatory |= {"visual-spec", "design"}
    if re.search(r"\b(research|unknown|investigate|evaluate|compare|regulation)\b", goal, re.I):
        mandatory.add("research")
    if not trivial:
        mandatory.add("brainstorm")
    return ({sid for sid, _ in STEPS} - conditional) | mandatory


def scope_evidence_changed(dependencies):
    return any(not Path(p).is_absolute() or Path(p).is_symlink() or not Path(p).is_file()
               or digest(p) != h for p, h in dependencies.items())


def prepare_start(records, work_id, project, goal, required=None, *, lane=None, ui=None):
    """Pure preflight: caller may hold both stores' locks before any mutation."""
    extras = scope_inputs(lane, ui, required)
    matches = [r for r in records if r["work_id"] == work_id]
    if len(matches) > 1:
        raise ValueError("duplicate protocol work ID")
    if matches:
        existing = matches[0]
        if existing["project"] != str(project) or existing["goal"] != goal:
            raise ValueError("work identity changed; reuse the original project and goal")
        if lane is not None and (existing.get("lane") != lane or existing.get("ui") != ui):
            raise ValueError("scope changed; use audited protocol-classify")
        if extras is not None and ("extra_required" not in existing or set(existing["extra_required"]) != extras):
            raise ValueError("extra requirements changed or unknown; use audited protocol-classify")
        if scope_evidence_changed(existing.get("scope_dependencies", {})):
            raise ValueError("scope evidence changed; use reviewed protocol-classify")
        return copy.deepcopy(existing), False
    extras = extras or set()
    needed = requirements(goal, lane, ui, extras)
    record = dict(work_id=work_id, project=str(project), goal=goal, created_at=now(), steps=[],
                  schema_version=2, lane=lane, ui=ui, policy_version=POLICY_VERSION,
                  scope_source="declared" if lane else "legacy-inferred", extra_required=sorted(extras))
    for i, (sid, command) in enumerate(STEPS):
        record["steps"].append(dict(step_id=sid, sequence=i + 1, skill=command, command=command,
            required=sid in needed, status="pending", evidence_path="", verify_command="", verified_at="",
            exception_reason="", dependencies={}, evidence_sha256="", verifier_exit=None))
    return record, True


def start(path, work_id, project, goal, required=None, *, lane=None, ui=None):
    with locked(path):
        records = read(path)
        record, created = prepare_start(records, work_id, project, goal, required, lane=lane, ui=ui)
        if created:
            write(path, records + [record])
        return record


def bound_file(ref, dependencies):
    if not isinstance(ref, dict):
        raise ValueError("bound evidence reference required")
    p = Path(ref.get("path", "")).expanduser()
    if not p.is_absolute() or p.is_symlink() or not p.is_file() or digest(p) != ref.get("sha256"):
        raise ValueError("bound evidence missing, changed, relative or symlinked")
    dependencies[str(p)] = ref["sha256"]
    return p


def reviewed_document(path, dependencies):
    document = json.loads(path.read_text())
    if not isinstance(document, dict):
        raise ValueError("scope document must be an object")
    review_ref = document.get("review")
    review = json.loads(bound_file(review_ref, dependencies).read_text())
    contract = {k: v for k, v in document.items() if k != "review"}
    if (review.get("verdict") != "APPROVE" or not str(review.get("reviewer", "")).strip()
            or review.get("contract_sha256") != object_digest(contract)):
        raise ValueError("independent review does not bind this exact contract")
    return document


def historical_extras(ref, record, dependencies):
    """Strict frozen JSON execution receipt, never execute supplied source/history."""
    p = bound_file(ref, dependencies)
    evidence = reviewed_document(p, dependencies)
    if any(evidence.get(k) != record[k] for k in ("work_id", "project", "goal", "created_at")):
        raise ValueError("historical provenance identity mismatch")
    module = bound_file(evidence.get("source_module"), dependencies)
    # Only the known legacy implementation's merged flags can be reconstructed here.
    if digest(module) != "edf83750d79ac87895b94e3bf816ff216e16475151490628a359416aa459eafb":
        raise ValueError("unknown historical module version; preserve required rows")
    raw = json.loads(bound_file(evidence.get("execution"), dependencies).read_text())
    locator = evidence.get("locator")
    if not isinstance(locator, list) or not locator:
        raise ValueError("exact frozen execution record locator required")
    try:
        for key in locator:
            raw = raw[key]
    except (KeyError, IndexError, TypeError):
        raise ValueError("execution locator missing") from None
    if not isinstance(raw, dict) or raw.get("kind") != "completed-protocol-start":
        raise ValueError("actual completed execution receipt required")
    execution_id = raw.get("execution_id")
    versions = raw.get("executed_source_versions")
    if (not isinstance(execution_id, str) or not execution_id.strip()
            or evidence.get("execution_id") != execution_id
            or not isinstance(versions, dict) or versions.get("module_sha256") != digest(module)):
        raise ValueError("original execution does not bind the executed module version")
    result = raw.get("result", {})
    original = result.get("protocol", {})
    if result.get("ok") is not True or any(original.get(k) != record[k] for k in ("work_id", "project", "goal", "created_at")):
        raise ValueError("historical successful creation result mismatch")
    if raw.get("caller") == "cli":
        cli = bound_file(evidence.get("source_cli"), dependencies)
        if digest(cli) != "022cb2a001fc5f0f5400901eb96937afe419f9f86de99dcafab582070b1ca9ed":
            raise ValueError("unknown historical CLI version; preserve required rows")
        if versions.get("cli_sha256") != digest(cli):
            raise ValueError("original execution does not bind the executed CLI version")
        tree = ast.parse(cli.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "development_protocol" and n.func.attr == "start"]
        if not calls or any(len(n.args) != 4 or n.keywords for n in calls):
            raise ValueError("historical CLI does not prove default extra requirements")
        argv = raw.get("argv")
        if not isinstance(argv, list) or not all(isinstance(v, str) for v in argv) or "protocol-start" not in argv:
            raise ValueError("complete historical CLI argv required")
        pos = argv.index("protocol-start")
        rest = argv[pos + 1:]
        allowed = {"--work-id": record["work_id"], "--project": record["project"], "--goal": record["goal"]}
        found = {}
        while rest:
            key = rest.pop(0)
            if key == "--json":
                continue
            if key not in allowed or key in found or not rest:
                raise ValueError("unknown or incomplete historical CLI arguments")
            found[key] = rest.pop(0)
        if found != allowed:
            raise ValueError("historical CLI identity mismatch")
        extras = set()
    elif raw.get("caller") == "api" and isinstance(raw.get("required"), list):
        extras = scope_inputs(None, None, raw["required"])
    else:
        raise ValueError("historical extra arguments unknown")
    return extras


def classify(path, work, lane, ui, evidence, reason, expected):
    scope_inputs(lane, ui)
    if lane is None or not reason.strip() or work.get("status") == "closed":
        raise ValueError("classification requires active work, explicit scope and reason")
    with locked(path):
        records = read(path)
        matches = [r for r in records if r["work_id"] == work.get("work_id")]
        if len(matches) != 1:
            raise ValueError("one existing protocol record required")
        original = matches[0]
        if any(work.get(k) != original[k] for k in ("work_id", "project", "goal")):
            raise ValueError("work identity mismatch")
        record = refresh(copy.deepcopy(original))
        if record_digest(record) != expected:
            raise ValueError("stale protocol record digest")
        p = Path(evidence).expanduser()
        deps = {}
        bound_file({"path": str(p), "sha256": digest(p)}, deps)
        scope = reviewed_document(p, deps)
        if (scope.get("work_id") != record["work_id"] or scope.get("project") != record["project"]
                or scope.get("goal_sha256") != hashlib.sha256(record["goal"].encode()).hexdigest()
                or scope.get("lane") != lane or scope.get("ui") is not ui or not str(scope.get("reason", "")).strip()):
            raise ValueError("reviewed scope identity mismatch")
        bound_file(scope.get("approved_plan"), deps)
        if not isinstance(scope.get("extra_required"), list):
            raise ValueError("explicit extra requirement list required")
        extras = scope_inputs(lane, ui, scope["extra_required"])
        old_lane = record.get("lane")
        if old_lane and (LANES[lane] < LANES[old_lane] or (record.get("ui") and not ui)):
            raise ValueError("declared lane/UI cannot be lowered")
        known = set(record.get("extra_required", []))
        protected = set(record.get("legacy_protected_required", []))
        if "extra_required" not in record or record.get("legacy_extras_unknown"):
            protected |= {s["step_id"] for s in record["steps"] if s["required"]}
            if scope.get("provenance"):
                known |= historical_extras(scope["provenance"], record, deps)
                protected = set()
        elif scope.get("provenance"):
            raise ValueError("known explicit extras cannot be reconstructed away")
        if not known <= extras:
            raise ValueError("extra required rows cannot be removed")
        binding = dict(lane=lane, ui=ui, extra_required=sorted(extras), protected=sorted(protected),
                       policy_version=POLICY_VERSION, dependencies=deps)
        if record.get("scope_binding") == binding and not record.get("scope_invalid"):
            return dict(ok=True, idempotent=True, record=record, **summary(record, record["work_id"]))
        needed = requirements(record["goal"], lane, ui, extras) | protected
        history = record.setdefault("history", [])
        history.append(dict(timestamp=now(), reason=reason, before=copy.deepcopy(original),
                            before_sha256=object_digest(original), scope_binding=binding))
        reopen = record.get("scope_binding") is not None
        for row in record["steps"]:
            if row["step_id"] in needed and not row["required"] and row["status"] == "not-applicable":
                reopen = True
            row["required"] = row["step_id"] in needed
            if reopen and row["status"] in TERMINAL:
                row.update(status="pending", exception_reason="Scope raised; repeat this step.")
        record.update(schema_version=2, lane=lane, ui=ui, scope_source="declared", extra_required=sorted(extras),
                      legacy_protected_required=sorted(protected), legacy_extras_unknown=bool(protected),
                      scope_binding=binding, scope_dependencies=deps, scope_invalid=False,
                      policy_version=POLICY_VERSION, updated_at=now())
        # Re-read bound files at the commit boundary; failures leave the original store intact.
        if scope_evidence_changed(deps):
            raise ValueError("scope evidence changed during classification")
        records[records.index(original)] = record
        write(path, records)
        return dict(ok=True, record=record, **summary(record, record["work_id"]))


def record_digest(record):
    clean = copy.deepcopy(record)
    for step_row in clean["steps"]:
        step_row.pop("next_step", None)
    return object_digest(clean)


def refresh(record):
    """Read-time invalidation: altered evidence or instrument reopens descendants."""
    scope_changed = scope_evidence_changed(record.get("scope_dependencies", {}))
    if scope_changed:
        record["scope_invalid"] = True
        for row in record["steps"]:
            if row["status"] in TERMINAL:
                row.update(status="pending", exception_reason="Scope evidence changed; reclassify and repeat.")
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
        ready=not open_steps and not record.get("scope_invalid", False),
        record_sha256=record_digest(record),
        lane=record.get("lane"), ui=record.get("ui"), scope_source=record.get("scope_source", "legacy-inferred"),
        scope_invalid=record.get("scope_invalid", False),
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
        if record.get("scope_invalid"):
            raise ValueError("scope evidence changed; reviewed classification required before proof")
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
