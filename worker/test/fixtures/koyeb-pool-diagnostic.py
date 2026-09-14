"""Test-container-only observer: fixed categories, no helper result changes."""
import errno
import hashlib
import json
import os
import sys

HELPER = "/usr/local/libexec/crabbox-koyeb-sandbox/project-state.py"
EXPECTED_HELPER_SHA256 = "25af5e99345ff1d6f2e45ce51c646804c8f09f2fd1d29ebdf3f5b723ba4226f3"
OUTPUT = "/tmp/crabbox-pool-diagnostic/events.jsonl"
FUNCTIONS = {"main", "pool_baseline", "pool_clean", "snapshot", "walk", "safe_path"}
REASONS = {
    "invalid runner state": "invalid_state",
    "runner has already been consumed": "already_consumed",
    "pool requires an empty project workspace": "workspace_not_empty",
    "browser profiles cannot enter the ready pool": "browser_profile_present",
    "runner home changed after clean bootstrap": "home_changed",
    "invalid pool claim": "invalid_claim",
    "invalid project state request": "invalid_request",
    "runner lease identity mismatch": "lease_mismatch",
    "clean baseline requires bootstrap authority": "invalid_baseline_authority",
    "repository state cannot enter a clean runner home": "home_repository_present",
    "project changed during checkpoint": "home_changed_during_snapshot",
    "project symlink leaves checkpoint scope": "home_symlink_invalid",
    "project contains unsupported filesystem state": "home_unsupported_entry",
    "project checkpoint exceeds entry limit": "home_entry_limit",
    "invalid project path": "home_path_invalid",
}
EXCEPTIONS = {"ValueError": "value_error", "OSError": "os_error", "PermissionError": "permission_error",
              "FileNotFoundError": "not_found", "FileExistsError": "already_exists",
              "BlockingIOError": "lock_blocked", "NotADirectoryError": "not_directory",
              "IsADirectoryError": "is_directory", "JSONDecodeError": "invalid_json",
              "DependencyError": "dependency_error", "KeyError": "missing_key", "TypeError": "type_error"}
ERRNOS = {"EACCES", "EPERM", "ENOENT", "EEXIST", "EAGAIN", "EWOULDBLOCK", "EIO", "ENOSPC",
          "EROFS", "ELOOP", "ENOTDIR", "EISDIR", "EINTR", "EINVAL", "EBADF", "ENOTSUP"}
operation = "baseline" if sys.argv[1:] == ["--record-clean-baseline"] else "request"
emitted = 0


def emit(stage, reason, exception="none", error_number=None):
    global emitted
    try:
        if emitted >= 32:
            return
        emitted += 1
        code = errno.errorcode.get(error_number) if isinstance(error_number, int) else None
        record = {"operation": operation, "stage": stage, "reason": reason, "exception": exception,
                  "errno": code if code in ERRNOS else "none" if error_number is None else "other_errno"}
        fd = os.open(OUTPUT, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())
        finally:
            os.close(fd)
    except Exception:
        pass  # An observation failure must never replace the helper's result.


def stage_for(function, line):
    # Line mapping is enabled only for EXPECTED_HELPER_SHA256. No source paths,
    # exception text, home inventory/content hashes or request data are emitted.
    if function == "pool_clean":
        for upper, stage in ((253, "state_directory"), (254, "lock_open"), (256, "lock_acquire"),
                             (263, "consumed_marker"), (266, "workspace_empty"), (270, "browser_absent"),
                             (271, "baseline_read"), (272, "home_snapshot"), (273, "home_integrity"),
                             (276, "claim_format"), (280, "claim_marker_write"), (281, "claim_marker_sync"),
                             (286, "claim_directory_sync"), (287, "claim_complete"), (289, "lock_close")):
            if line <= upper:
                return stage
        return "pool_dispatch"
    if function == "pool_baseline":
        return "baseline_capture"
    if function in ("snapshot", "walk", "safe_path"):
        return "home_snapshot"
    for upper, stage in ((297, "baseline_request"), (300, "request_path"), (307, "request_read"),
                         (310, "request_remove"), (315, "lease_identity")):
        if line <= upper:
            return stage
    return "pool_dispatch"


def trace(frame, event, arg):
    global operation
    try:
        function = frame.f_code.co_name
        if frame.f_code.co_filename != HELPER or function not in FUNCTIONS:
            return None
        frame.f_trace_lines = False
        if event == "call":
            if function == "pool_baseline":
                operation = "baseline"
                emit("baseline_capture", "entered")
            elif function == "pool_clean":
                operation = "pool_claim" if frame.f_locals.get("claim") is not None else "pool_check"
                emit("pool_dispatch", "entered")
        elif event == "return" and function == "pool_clean" and isinstance(arg, dict):
            state = arg.get("state")
            if state in ("clean", "claimed"):
                emit("claim_complete", state)
        elif event == "exception":
            if function == "main":
                request = frame.f_locals.get("request")
                action = request.get("action") if isinstance(request, dict) else None
                if action in ("capture", "restore"):
                    return None
                if action in ("pool-check", "pool-claim"):
                    operation = "pool_check" if action == "pool-check" else "pool_claim"
            elif operation == "request":
                return trace  # Do not observe project capture/restore internals.
            error = arg[1]
            if isinstance(error, (StopIteration, GeneratorExit)):
                return trace
            reason = "unclassified_error"
            if type(error) is ValueError and error.args and isinstance(error.args[0], str):
                reason = REASONS.get(error.args[0], reason)
            elif type(error).__name__ == "DependencyError" and getattr(error, "code", None) == "checkpoint_unpreserved_content_limit":
                reason = "unpreserved_content_limit"
            emit(stage_for(function, frame.f_lineno), reason,
                 EXCEPTIONS.get(type(error).__name__, "other_exception"), getattr(error, "errno", None))
        return trace
    except Exception:
        emit("observer", "observer_error")
        return trace


def activate():
    if sys.argv[0] != HELPER or os.geteuid() != 0:
        return
    try:
        with open(HELPER, "rb") as source:
            matches = hashlib.sha256(source.read()).hexdigest() == EXPECTED_HELPER_SHA256
        if not matches:
            emit("observer", "source_mismatch")
            return
        emit("observer", "ready")
        sys.settrace(trace)
    except Exception:
        emit("observer", "observer_error")


activate()
