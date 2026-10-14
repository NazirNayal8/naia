"""Sequential local execution and Slurm dependency submission with immutable attempts."""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import sys
import uuid

from .storage import NAIAError, atomic_text, digest, file_digest, inside, locked, now, read_json, write_json
from .suites import Suites, definition_digest


def substitute(value, variables):
    def replace(match):
        key = match[1]
        if key not in variables:
            raise NAIAError(f"Unknown command placeholder: {key}")
        return str(variables[key])
    return re.sub(r"\{([A-Za-z][A-Za-z0-9_]*)\}", replace, value)


def build_plan(project, data, cell, attempt, profile, resume_from="", evaluation_attempts=None):
    run_dir = project.path(f".lab/state/runs/{data['id']}/{cell['id']}/{attempt}")
    artifact = inside(run_dir, data["artifact"])
    variables = {**cell.get("parameters", {}), "project": str(project.root),
                 "python": profile.get("command_python", sys.executable), "run_dir": str(run_dir),
                 "artifact": str(artifact), "cell": cell["id"], "suite": data["id"], "resume_from": resume_from}
    def stage(command, metrics="", resume=False):
        values = {**variables, "metrics": metrics}
        if metrics:
            values["python"] = profile.get("evaluation_python", values["python"])
        argv = command.get("resume_argv") if resume and command.get("resume_argv") else command["argv"]
        prefix = profile.get("evaluation_command_prefix", profile.get("command_prefix", [])) if metrics else profile.get("command_prefix", [])
        return {"argv": prefix + [substitute(arg, values) for arg in argv],
                "environment": {key: substitute(value, values) for key, value in command.get("environment", {}).items()},
                "timeout_seconds": command.get("timeout_seconds")}
    return {
        "run_dir": str(run_dir.relative_to(project.root)),
        "artifact": str(artifact.relative_to(project.root)),
        "training": stage(data["training"], resume=bool(resume_from)),
        "evaluation": {p["id"]: stage(p["command"], str(run_dir / f"metrics-{p['id']}-{(evaluation_attempts or {}).get(p['id'], 'initial')}.json")) for p in data["evaluation"]},
    }


def update_record(project, record_path, mutate):
    target = project.path(record_path)
    with locked(target.with_suffix(".lock")):
        record = read_json(target)
        mutate(record)
        record["updated_at"] = now()
        write_json(target, record)
    return record


def run_stage(project, record_path, stage, evaluation=None):
    target = project.path(record_path)
    # Protect against two workers for the same stage, not only two submitters.
    lock_id = "evaluation-" + evaluation if evaluation else "training"
    from .storage import name
    if evaluation:
        name(evaluation)
    with locked(target.parent / (lock_id + ".lock"), timeout=0):
        return _run_stage(project, record_path, stage, evaluation)


def _run_stage(project, record_path, stage, evaluation=None):
    record = read_json(project.path(record_path))
    data = record["definition"]
    if definition_digest(data) != record["definition_hash"]:
        raise NAIAError("Recorded definition fingerprint is invalid")
    entry = record["evaluation"][evaluation] if evaluation else record["training"]
    plan = record["plan"]["evaluation"][evaluation] if evaluation else record["plan"]["training"]
    if entry["status"] == "complete":
        return record
    artifact = project.path(record["artifact"])
    run_dir = project.path(record["plan"]["run_dir"])
    raw = project.path(entry["raw_metrics"]) if evaluation else None
    if evaluation:
        if record["training"]["status"] != "complete" or not artifact.is_file() or file_digest(artifact) != record.get("artifact_sha256"):
            raise NAIAError("Evaluation requires a verified training artifact")
        if raw.exists():
            raise NAIAError("Existing raw metrics require a fresh evaluation attempt; never reuse stale metrics")
    def mark(status, **extra):
        def mutate(current):
            item = current["evaluation"][evaluation] if evaluation else current["training"]
            item.update(status=status, **extra)
        return update_record(project, record_path, mutate)
    mark("running", started_at=now(), host=socket.gethostname(), manager_pid=os.getpid())
    log = run_dir / f"{stage}.log"
    try:
        with log.open("ab") as output:
            process = subprocess.Popen(plan["argv"], cwd=project.root,
                                       env={**os.environ, **plan["environment"]}, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != "nt")
            mark("running", pid=process.pid)
            try:
                code = process.wait(timeout=plan["timeout_seconds"])
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                raise NAIAError(f"Stage timed out: {stage}")
            except BaseException:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
                raise
        if code:
            raise NAIAError(f"{stage} exited {code}; see {log}")
        if not evaluation:
            if not artifact.is_file() or not artifact.stat().st_size:
                raise NAIAError("Training exited successfully without its declared nonempty artifact")
            checksum = file_digest(artifact)
            def finish(current):
                current["artifact_sha256"] = checksum
                current["training"].update(status="complete", finished_at=now())
            result = update_record(project, record_path, finish)
        else:
            if file_digest(artifact) != record["artifact_sha256"]:
                raise NAIAError("Evaluation modified the training artifact")
            profile = next(p for p in data["evaluation"] if p["id"] == evaluation)
            raw_values = read_json(raw)
            metrics = {}
            for key, spec in profile["metrics"].items():
                value = raw_values
                for component in spec["path"].split("."):
                    if not isinstance(value, dict) or component not in value:
                        raise NAIAError(f"Missing metric: {spec['path']}")
                    value = value[component]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise NAIAError(f"Metric {key} must be finite and numeric")
                metrics[key] = value
            result_file = run_dir / f"result-{evaluation}-{entry['attempt']}.json"
            identity = {"suite": record["suite"], "cell": record["cell"], "attempt": record["attempt"],
                        "definition_hash": record["definition_hash"], "profile": evaluation,
                        "evaluation_attempt": entry["attempt"],
                        "artifact_sha256": record["artifact_sha256"]}
            write_json(result_file, {"identity": identity, "metrics": metrics, "evaluated_at": now()})
            result = mark("complete", finished_at=now(), result=str(result_file.relative_to(project.root)))
    except KeyboardInterrupt:
        mark("failed", error="Interrupted by user; child process group terminated", finished_at=now())
        raise
    except (OSError, ValueError) as exc:
        mark("failed", error=str(exc), finished_at=now())
        raise NAIAError(str(exc)) from exc
    finally:
        Suites(project).sync()
    return result


def scheduler_state(job_id):
    """Unknown scheduler state is not evidence that resubmission is safe."""
    try:
        queue = subprocess.run(["squeue", "--noheader", "--jobs", str(job_id), "--format=%T|%r"], capture_output=True, text=True, timeout=15)
        if queue.returncode == 0 and queue.stdout.strip():
            status, _, reason = queue.stdout.strip().splitlines()[0].partition("|")
            if reason == "DependencyNeverSatisfied":
                return "dependency_failed"
            return {"RUNNING": "running", "PENDING": "queued", "CONFIGURING": "queued", "COMPLETING": "running", "SUSPENDED": "running"}.get(status, "unknown")
        accounting = subprocess.run(["sacct", "--noheader", "--parsable2", "--jobs", str(job_id), "--format=JobIDRaw,State"], capture_output=True, text=True, timeout=15)
        if accounting.returncode != 0:
            return "unknown"
        for line in accounting.stdout.splitlines():
            identifier, _, state = line.partition("|")
            if identifier != str(job_id):
                continue
            state = state.split()[0].rstrip("+")
            if state in {"FAILED", "TIMEOUT", "CANCELLED", "OUT_OF_MEMORY", "NODE_FAIL", "PREEMPTED", "BOOT_FAIL", "DEADLINE"}:
                return "failed"
            if state == "COMPLETED":
                return "finished_without_result"
        return "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def reconcile(project, record_path):
    record = read_json(project.path(record_path))
    if record["backend_profile"]["kind"] != "slurm":
        return record
    updates = {}
    for key, entry in [(None, record["training"]), *record["evaluation"].items()]:
        if entry["status"] in {"queued", "running", "submitting", "unknown"}:
            state = scheduler_state(entry["job_id"]) if entry.get("job_id") else "unknown"
            updates[key] = state
    def mutate(current):
        for key, state in updates.items():
            item = current["training"] if key is None else current["evaluation"][key]
            if item["status"] in {"complete", "failed"}:
                continue
            item["status"] = state
            if state == "finished_without_result":
                item["error"] = "Scheduler reports success but the worker did not verify an artifact/result"
    return update_record(project, record_path, mutate)


def submit_stage(project, record_path, evaluation=None, dependency=None):
    record = read_json(project.path(record_path))
    profile = record["backend_profile"]
    stage = "eval-" + evaluation if evaluation else "train"
    resources = profile.get("evaluation_resources", profile.get("resources", {})) if evaluation else profile.get("resources", {})
    arguments = ["sbatch", "--parsable", f"--job-name=naia-{record['suite']}-{record['cell']}-{stage}",
                 f"--chdir={project.root}", f"--output={project.path(record['plan']['run_dir'])}/{stage}-%j.log"]
    arguments += [f"--{key}={value}" for key, value in resources.items()]
    if dependency:
        arguments.append(f"--dependency=afterok:{dependency}")
    worker = [profile["management_python"], "-m", "naia.cli", "--project", str(project.root), "_worker", record_path]
    if evaluation:
        worker += ["--profile", evaluation]
    script_relative = str(Path(record["plan"]["run_dir"]) / f"{stage}.sh")
    script = project.path(script_relative)
    script_text = "#!/usr/bin/env bash\nset -euo pipefail\nexec " + shlex.join(worker) + "\n"
    arguments.append(str(script))
    def mark(status, **values):
        def mutate(current):
            item = current["evaluation"][evaluation] if evaluation else current["training"]
            if item["status"] not in {"running", "complete", "failed"}:
                item["status"] = status
            item.update(values)
        return update_record(project, record_path, mutate)
    mark("submitting", submit_argv=arguments, submission_script=script_relative, submitted_at=now())
    try:
        if script.exists():
            if script.read_text(encoding="utf-8") != script_text:
                raise NAIAError("Existing submission script differs; inspect it before retrying")
        else:
            atomic_text(script, script_text)
    except (OSError, ValueError) as exc:
        mark("failed", error=f"Could not prepare Bash job script: {exc}")
        raise NAIAError(f"Could not prepare Bash job script: {exc}") from exc
    try:
        submitted = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        mark("unknown", error=f"Submission outcome uncertain: {exc}")
        raise NAIAError("Submission outcome uncertain; inspect before retrying") from exc
    identifier = submitted.stdout.strip().split(";")[0]
    if submitted.returncode:
        mark("failed", error=submitted.stderr.strip())
        raise NAIAError(f"sbatch failed: {submitted.stderr.strip()}")
    if not identifier.isdigit():
        mark("unknown", error=f"Unrecognized submission response: {submitted.stdout}")
        raise NAIAError("Unknown job ID; do not blindly resubmit")
    mark("queued", job_id=identifier, dependency=dependency)
    return identifier


def prepare_attempt(project, data, cell, profile, resume_from=""):
    attempt = uuid.uuid4().hex[:16]
    plan = build_plan(project, data, cell, attempt, profile, resume_from)
    directory = project.path(plan["run_dir"])
    directory.mkdir(parents=True)
    record_path = str((directory / "record.json").relative_to(project.root))
    record = {"schema_version": 1, "suite": data["id"], "cell": cell["id"], "attempt": attempt,
              "definition_hash": definition_digest(data), "definition": copy.deepcopy(data), "plan": plan,
              "backend_profile": profile, "created_at": now(), "artifact": plan["artifact"],
              "context_revision": project.load()["revision"], "training": {"status": "pending"},
              "context_snapshot": project.load(),
              "resume_from": {"path": resume_from, "sha256": file_digest(resume_from)} if resume_from else None,
              "evaluation": {p["id"]: {"status": "pending", "attempt": "initial",
                             "raw_metrics": str((directory / f"metrics-{p['id']}-initial.json").relative_to(project.root))}
                             for p in data["evaluation"]}, "record_path": record_path}
    write_json(project.path(record_path), record)
    write_json(directory.parent / "current.json", {"record": record_path})
    return record


def retry_evaluation(project, record, key):
    """Preserve old evidence and assign new output paths without retraining."""
    data = record["definition"]
    cell = next(c for c in data["cells"] if c["id"] == record["cell"])
    attempt = uuid.uuid4().hex[:16]
    updated_plan = build_plan(project, data, cell, record["attempt"], record["backend_profile"],
                              evaluation_attempts={key: attempt})["evaluation"][key]
    directory = project.path(record["plan"]["run_dir"])
    def mutate(current):
        previous = current["evaluation"][key]
        history = previous.get("history", []) + [{"entry": {k: v for k, v in previous.items() if k != "history"},
                                                  "plan": current["plan"]["evaluation"][key]}]
        current["evaluation"][key] = {"status": "pending", "attempt": attempt, "history": history,
                                     "raw_metrics": str((directory / f"metrics-{key}-{attempt}.json").relative_to(project.root))}
        current["plan"]["evaluation"][key] = updated_plan
    return update_record(project, record["record_path"], mutate)


def _launch_details(record, training_action, evaluation_actions):
    def entry(values, action):
        if action == "completed" and values["status"] != "complete":
            action = values["status"]
        elif (action in {"submitted", "resumed"} and not values.get("job_id")
              and values["status"] != "complete"):
            action = values["status"]
        return {"status": values["status"], "action": action,
                **{key: values[key] for key in ("job_id", "dependency", "error") if key in values}}
    return {"attempt": record["attempt"], "record_path": record["record_path"],
            "training": entry(record["training"], training_action),
            "evaluation": {key: entry(value, evaluation_actions.get(key, "not-requested"))
                           for key, value in record["evaluation"].items()}}


def launch(project, suite_id, *, backend="local", dry_run=False, auto_eval=True, retry=False, cell_id=None, evaluate_only=False, evaluation_id=None, on_outcome=None):
    suites = Suites(project)
    data = suites.load(suite_id, approved=not evaluate_only)
    if evaluate_only and (data.get("status") not in {"approved", "sealed"} or not data.get("approval", {}).get("by")):
        raise NAIAError("Only approved suites may be evaluated")
    profile = project.execution_ready(backend)
    # Registration is an explicit preflight contract. Dry runs never repair state.
    registry = read_json(project.directory / "state/registry.json")
    if suite_id not in {s["id"] for s in registry["suites"]}:
        raise NAIAError("Suite is not registered; run naia sync")
    selected = [c for c in data["cells"] if cell_id is None or c["id"] == cell_id]
    if not selected:
        raise NAIAError("Cell selector matched no cells")
    if evaluation_id and evaluation_id not in {p["id"] for p in data["evaluation"]}:
        raise NAIAError("Unknown evaluation profile")
    summary = {"suite": suite_id, "backend": backend, "backend_kind": profile["kind"],
               "evaluate_only": evaluate_only, "auto_evaluate": auto_eval or evaluate_only}
    if dry_run:
        plans = []
        for cell in selected:
            plan = {"cell": cell["id"], **build_plan(project, data, cell, "DRY-RUN", profile)}
            plan["evaluation"] = {key: value for key, value in plan["evaluation"].items()
                                  if (auto_eval or evaluate_only) and (not evaluation_id or key == evaluation_id)}
            plans.append(plan)
        return {**summary, "dry_run": True, "plans": plans}
    outcomes = []
    for cell in selected:
        record = None
        training_action = "not-requested" if evaluate_only else "blocked"
        evaluation_actions = {}
        try:
            with locked(project.path(f".lab/state/locks/run-{suite_id}-{cell['id']}.lock"), timeout=0):
                record = suites.pointer(suite_id, cell["id"])
                if record:
                    record = reconcile(project, record["record_path"])
                    if record["definition_hash"] != definition_digest(data):
                        raise NAIAError("Definition changed; preserve provenance by creating a new suite")
                    if record["backend_profile"] != profile:
                        raise NAIAError("Existing attempt uses another backend profile; do not duplicate cross-backend work")
                if evaluate_only and (not record or record["training"]["status"] != "complete"):
                    raise NAIAError("Training is not verified complete")
                status = record["training"]["status"] if record else None
                if status in {"unknown", "submitting", "finished_without_result"}:
                    raise NAIAError("Uncertain training state requires inspection, not resubmission")
                if status in {"failed", "dependency_failed"} and not retry:
                    raise NAIAError("Use --retry to create a new attempt for failed work")
                if not evaluate_only and status in {"queued", "running", "complete"}:
                    training_action = "reused"
                if not record or status in {"failed", "dependency_failed"}:
                    resume_from = ""
                    if record and data.get("resume_artifact") and data["training"].get("resume_argv"):
                        candidate = inside(project.path(record["plan"]["run_dir"]), data["resume_artifact"])
                        if candidate.is_file():
                            resume_from = str(candidate)
                    record = prepare_attempt(project, data, cell, profile, resume_from)
                    training_action = "resumed" if resume_from else (
                        "completed" if profile["kind"] == "local" else "submitted")
                    if profile["kind"] == "local":
                        record = run_stage(project, record["record_path"], "train")
                    else:
                        submit_stage(project, record["record_path"])
                        record = read_json(project.path(record["record_path"]))
                dependency = record["training"].get("job_id") if record["training"]["status"] != "complete" else None
                if auto_eval or evaluate_only:
                    for evaluation in data["evaluation"]:
                        key = evaluation["id"]
                        if evaluation_id and key != evaluation_id:
                            continue
                        latest = read_json(project.path(record["record_path"]))
                        state = latest["evaluation"][key]["status"]
                        if state == "complete":
                            suites.checked_result(latest, evaluation)
                            evaluation_actions[key] = "reused"
                            continue
                        if state in {"queued", "running"}:
                            evaluation_actions[key] = "reused"
                            continue
                        if state != "pending":
                            # New output filenames avoid reusing metrics from a failed evaluation.
                            if not retry or state in {"unknown", "submitting", "finished_without_result"}:
                                raise NAIAError(f"Evaluation {key}: {state}; inspect or explicitly retry")
                            if state not in {"failed", "dependency_failed"}:
                                raise NAIAError(f"Evaluation {key} is not safely retryable")
                            retry_evaluation(project, latest, key)
                        if profile["kind"] == "local":
                            evaluation_actions[key] = "completed"
                            run_stage(project, record["record_path"], "eval-" + key, key)
                        else:
                            evaluation_actions[key] = "submitted"
                            submit_stage(project, record["record_path"], key, dependency)
                latest = read_json(project.path(record["record_path"]))
                outcome = {"cell": cell["id"], "status": "tracked",
                           **_launch_details(latest, training_action, evaluation_actions)}
        except NAIAError as exc:
            outcome = {"cell": cell["id"], "status": "error", "error": str(exc)}
            if record:
                try:
                    latest = read_json(project.path(record["record_path"]))
                    outcome.update(_launch_details(latest, training_action, evaluation_actions))
                except NAIAError:
                    pass
        outcome = {**summary, **outcome}
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)
    suites.sync()
    return {**summary, "outcomes": outcomes, "ok": all(o["status"] != "error" for o in outcomes)}
