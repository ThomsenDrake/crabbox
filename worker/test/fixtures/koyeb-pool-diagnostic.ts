import { fileURLToPath } from "node:url";

type Docker = (args: string[]) => Promise<string>;
const directory = "/tmp/crabbox-pool-diagnostic";
const source = fileURLToPath(new URL("./koyeb-pool-diagnostic.py", import.meta.url));
const vocabulary = {
  operation: ["baseline", "request", "pool_check", "pool_claim"],
  stage: [
    "observer",
    "state_directory",
    "lock_open",
    "lock_acquire",
    "consumed_marker",
    "workspace_empty",
    "browser_absent",
    "baseline_read",
    "home_snapshot",
    "home_integrity",
    "claim_format",
    "claim_marker_write",
    "claim_marker_sync",
    "claim_directory_sync",
    "claim_complete",
    "lock_close",
    "pool_dispatch",
    "baseline_capture",
    "baseline_request",
    "request_path",
    "request_read",
    "request_remove",
    "lease_identity",
  ],
  reason: [
    "entered",
    "clean",
    "claimed",
    "ready",
    "source_mismatch",
    "observer_error",
    "unclassified_error",
    "unpreserved_content_limit",
    "invalid_state",
    "already_consumed",
    "workspace_not_empty",
    "browser_profile_present",
    "home_changed",
    "invalid_claim",
    "invalid_request",
    "lease_mismatch",
    "invalid_baseline_authority",
    "home_repository_present",
    "home_changed_during_snapshot",
    "home_symlink_invalid",
    "home_unsupported_entry",
    "home_entry_limit",
    "home_path_invalid",
  ],
  exception: [
    "none",
    "value_error",
    "os_error",
    "permission_error",
    "not_found",
    "already_exists",
    "lock_blocked",
    "not_directory",
    "is_directory",
    "invalid_json",
    "dependency_error",
    "missing_key",
    "type_error",
    "other_exception",
  ],
  errno: [
    "none",
    "other_errno",
    "EACCES",
    "EPERM",
    "ENOENT",
    "EEXIST",
    "EAGAIN",
    "EWOULDBLOCK",
    "EIO",
    "ENOSPC",
    "EROFS",
    "ELOOP",
    "ENOTDIR",
    "EISDIR",
    "EINTR",
    "EINVAL",
    "EBADF",
    "ENOTSUP",
  ],
};

export const unavailablePoolDiagnostic = () => ({ event: "runner_pool_diagnostic_unavailable" });

// Reconstruct only fixed vocabulary. Never echo an untrusted JSON field, line,
// exception, path, profile, claim, content hash or credential into the CI log.
export function projectPoolDiagnostic(line: string) {
  try {
    const value: unknown = JSON.parse(line);
    if (!value || typeof value !== "object" || Array.isArray(value))
      return unavailablePoolDiagnostic();
    const result: Record<string, string> = { event: "runner_pool_diagnostic" };
    for (const [key, allowed] of Object.entries(vocabulary)) {
      const field: unknown = (value as Record<string, unknown>)[key];
      if (typeof field !== "string" || !allowed.includes(field)) return unavailablePoolDiagnostic();
      result[key] = field;
    }
    return result;
  } catch {
    return unavailablePoolDiagnostic();
  }
}

export async function installPoolDiagnostic(docker: Docker, container: string) {
  await docker(["exec", container, "install", "-d", "-m", "0700", directory]);
  await docker(["cp", source, `${container}:${directory}/crabbox_pool_diagnostic.py`]);
  // Python's startup loader observes the unmodified packaged helper. Exceptions
  // in the observer/loader are isolated from the helper and its terminal code.
  const loader = `import sys; exec(${JSON.stringify(
    `try:\n sys.path.append('${directory}')\n import crabbox_pool_diagnostic\nexcept Exception:\n pass`,
  )})\n`;
  await docker([
    "exec",
    container,
    "/usr/bin/python3",
    "-c",
    [
      "import pathlib,site,sys",
      "candidates=[p for p in site.getsitepackages() if p.startswith('/usr/local/')]",
      "assert candidates",
      "destination=pathlib.Path(candidates[0]); destination.mkdir(parents=True,exist_ok=True)",
      "(destination/'crabbox_pool_diagnostic.pth').write_text(sys.argv[1])",
    ].join(";"),
    loader,
  ]);
}

export async function readPoolDiagnostics(docker: Docker, container: string) {
  const output = await docker(["exec", container, "cat", `${directory}/events.jsonl`]);
  const lines = output.split("\n");
  if (lines.length > 128) return [unavailablePoolDiagnostic()];
  return lines.map(projectPoolDiagnostic);
}
