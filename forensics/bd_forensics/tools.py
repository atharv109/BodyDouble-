"""The fixed tool list (PRD "Tool list"): the planner's only choices.

Each tool is code run against the read-only mount. The twin builds the exact
script for a ToolCall, executes it, and returns a ToolResult whose `code` is
that exact script - so the recorded Step is the script that actually ran.

Scripts are stdlib-only Python that take the mount as argv[1] and only READ
it. They run unchanged on the Alpine twin, in the debian demo containers,
and on the test host against demo/victim/ and demo/clean/.
"""
from __future__ import annotations

import subprocess
import sys
import time

from contracts.models import Artifact, ToolCall, ToolName, ToolResult

# args each tool requires (planner-provided; validated in code before running)
REQUIRED_ARGS: dict[ToolName, tuple[str, ...]] = {
    ToolName.extract: ("path",),
    ToolName.detonate: ("path",),
    ToolName.custom_script: ("code",),
}


def valid_args(tool: ToolName, args: dict) -> bool:
    """Code-side validation: every required arg present, and file paths stay
    inside the mount (a planner-proposed '..' escape must never run)."""
    if not all(k in args for k in REQUIRED_ARGS.get(tool, ())):
        return False
    if "path" in args and not is_safe_rel_path(str(args["path"])):
        return False
    return True


def is_safe_rel_path(path: str) -> bool:
    p = path.strip().strip("/")
    if not p or p.startswith("/") or ".." in p.split("/"):
        return False
    # quotes let a path break out of generated script source; ':' and '\'
    # are Windows drive/UNC forms that pathlib joins treat as absolute
    if any(c in p for c in ':"\\\'') or any(ord(c) < 32 for c in p):
        return False
    return True


# ---------------------------------------------------------------- scripts
OS_FACTS_CODE = '''\
import sys
from pathlib import Path

mount = Path(sys.argv[1])

def read(rel, default=""):
    try:
        return (mount / rel).read_text(errors="replace")
    except OSError:
        return default

print("== os-release ==")
print(read("etc/os-release", "(missing)") or "(missing)")
print("== hostname ==")
print(read("etc/hostname", "(missing)").strip() or "(missing)")
users = []
for line in read("etc/passwd").splitlines():
    parts = line.split(":")
    if len(parts) >= 7 and parts[6] not in ("/usr/sbin/nologin", "/bin/false"):
        users.append(parts[0])
print("== login-capable users ==")
print(", ".join(users) if users else "(none)")
pkgs = sorted(
    line.split(":", 1)[1].strip()
    for line in read("var/lib/dpkg/status").splitlines()
    if line.startswith("Package:")
)
print(f"== installed packages ({len(pkgs)}) ==")
print(", ".join(pkgs))
'''

PERSISTENCE_SCAN_CODE = '''\
import sys
from pathlib import Path

mount = Path(sys.argv[1])
LIMIT = 4000

def show(rel):
    p = mount / rel
    if p.is_dir():
        for child in sorted(p.rglob("*")):
            if child.is_file():
                show(str(child.relative_to(mount)))
        return
    if not p.is_file():
        return
    print(f"---- {rel} ----")
    try:
        text = p.read_text(errors="replace")
    except OSError as exc:
        print(f"(unreadable: {exc})")
        return
    print(text[:LIMIT], "...[truncated]" if len(text) > LIMIT else "")

def read(rel):
    try:
        return (mount / rel).read_text(errors="replace")
    except OSError:
        return ""

show("etc/crontab")
show("etc/cron.d")
show("var/spool/cron/crontabs")
show("etc/rc.local")
show("etc/ld.so.preload")
show("etc/systemd/system")
show("etc/profile")
show("etc/profile.d")
show("root/.profile")
show("root/.bashrc")
for line in read("etc/passwd").splitlines():
    parts = line.split(":")
    if len(parts) >= 6 and parts[5].startswith("/home"):
        show(parts[5].lstrip("/") + "/.profile")
        show(parts[5].lstrip("/") + "/.bashrc")
'''

AUTH_SCAN_CODE = '''\
import sys
from pathlib import Path

mount = Path(sys.argv[1])
LIMIT = 4000

def read(rel):
    try:
        return (mount / rel).read_text(errors="replace")
    except OSError:
        return ""

def show(rel):
    p = mount / rel
    if p.is_dir():
        for child in sorted(p.rglob("*")):
            if child.is_file():
                show(str(child.relative_to(mount)))
        return
    if not p.is_file():
        return
    print(f"---- {rel} ----")
    text = read(rel)
    print(text[:LIMIT], "...[truncated]" if len(text) > LIMIT else "")

for line in read("etc/passwd").splitlines():
    parts = line.split(":")
    if len(parts) >= 6:
        show(parts[5].strip("/") + "/.ssh/authorized_keys")
show("etc/sudoers")
show("etc/sudoers.d")
log = read("var/log/auth.log")
print("---- var/log/auth.log (last 40 lines) ----")
print("\\n".join(log.splitlines()[-40:]))
'''

RECENT_FILES_CODE = '''\
import datetime
import os
import sys
import time
from pathlib import Path

mount = Path(sys.argv[1])
window_h = __WINDOW_H__
now = time.time()
skip = ("var/lib/dpkg", "var/lib/apt", "var/cache", "var/log", "usr/share/doc", "usr/lib")
count = 0
for root, dirs, files in os.walk(mount):
    rel_root = os.path.relpath(root, mount).replace("\\\\", "/")
    if rel_root == ".":
        dirs[:] = [d for d in dirs if d not in ("proc", "sys", "dev", "run")]
    for name in files:
        full = Path(root) / name
        rel = os.path.relpath(full, mount).replace("\\\\", "/")
        if rel.startswith(skip):
            continue
        try:
            st = full.stat()
        except OSError:
            continue
        age_h = (now - st.st_mtime) / 3600
        if age_h <= window_h:
            ts = datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc)
            print(f"{ts.isoformat()} {rel}")
            count += 1
print(f"total: {count} files changed in the last {window_h}h (package-manager dirs excluded)")
'''

BINARY_INTEGRITY_CODE = '''\
import hashlib
import sys
from pathlib import Path

mount = Path(sys.argv[1])
info = mount / "var/lib/dpkg/info"
ok = mismatch = missing = 0
if not info.is_dir():
    print("no dpkg info directory on the disk")
    raise SystemExit(0)
for md5file in sorted(info.glob("*.md5sums")):
    for line in md5file.read_text(errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        recorded, rel = parts[0], parts[1].lstrip("*").strip()
        target = mount / rel
        if not target.is_file():
            missing += 1
            continue
        try:
            actual = hashlib.md5(target.read_bytes()).hexdigest()
        except OSError as exc:
            print(f"UNREADABLE {rel}: {exc}")
            continue
        if actual == recorded:
            ok += 1
        else:
            mismatch += 1
            print(f"MISMATCH {rel} (recorded {recorded}, actual {actual})")
print(f"summary: {ok} ok, {mismatch} mismatched, {missing} missing")
'''

LISTENER_CONFIG_CODE = '''\
import sys
from pathlib import Path

mount = Path(sys.argv[1])
found = 0
for rel_dir in ("etc/systemd/system", "lib/systemd/system", "usr/lib/systemd/system"):
    d = mount / rel_dir
    if not d.is_dir():
        continue
    for unit in sorted(d.rglob("*")):
        if not unit.is_file() or unit.suffix not in (".service", ".socket"):
            continue
        try:
            lines = unit.read_text(errors="replace").splitlines()
        except OSError:
            continue
        interesting = [l for l in lines if l.lstrip().startswith(("Listen", "ExecStart"))]
        if interesting:
            found += 1
            print(f"---- {unit.relative_to(mount).as_posix()} ----")
            print("\\n".join(interesting))
if not found:
    print("no configured listeners found in unit files")
'''

EXTRACT_CODE = '''\
import hashlib
import sys
from pathlib import Path

mount = Path(sys.argv[1])
orig = sys.argv[2]  # travels as argv, never interpolated into script source
rel = orig.strip().lstrip("/")
if not rel or ".." in rel.split("/"):
    print(f"refused unsafe path: {orig}")
    raise SystemExit(2)
full = mount / rel
resolved = full.resolve()
if not resolved.is_relative_to(mount.resolve()):
    # a symlink on the cloned disk must not read through to the twin's
    # own rootfs (or, in tests, the host's)
    print(f"refused: {orig} resolves outside the mount")
    raise SystemExit(2)
try:
    data = resolved.read_bytes()
except OSError as exc:
    print(f"extract failed: {exc}")
    raise SystemExit(2)
print(f"extracted {orig}")
print(f"sha256 {hashlib.sha256(data).hexdigest()}")
print("---- first 2000 chars ----")
print(data[:2000].decode(errors="replace"))
'''

SCRIPTS: dict[ToolName, str] = {
    ToolName.os_facts: OS_FACTS_CODE,
    ToolName.persistence_scan: PERSISTENCE_SCAN_CODE,
    ToolName.auth_scan: AUTH_SCAN_CODE,
    ToolName.recent_files: RECENT_FILES_CODE,
    ToolName.binary_integrity: BINARY_INTEGRITY_CODE,
    ToolName.listener_config: LISTENER_CONFIG_CODE,
    ToolName.extract: EXTRACT_CODE,
}


def build_code(call: ToolCall) -> str:
    """The exact script a step runs. Triage tools come from this fixed set;
    custom_script is the planner's own (validated) Python, run sandboxed.
    Model-provided values (paths, windows) never enter script source:
    paths travel as argv (see step_argv), windows as repr(float)."""
    if call.tool == ToolName.custom_script:
        return str(call.args["code"])
    if call.tool == ToolName.detonate:
        raise ValueError("detonate is executed by the sandbox, not built as a script")
    code = SCRIPTS[call.tool]
    if call.tool == ToolName.recent_files:
        try:
            window_h = float(call.args.get("window_h", 72))
        except (TypeError, ValueError):
            window_h = 72.0  # planner garbage must never crash the step
        code = code.replace("__WINDOW_H__", repr(window_h))
    return code


def step_argv(call: ToolCall) -> list[str]:
    """Out-of-band script arguments after the mount (argv[2:]). The extract
    path arrives here so a crafted path can never inject into script source."""
    if call.tool == ToolName.extract:
        return [str(call.args["path"])]
    return []


def run_code(
    code: str, mount: str, timeout_s: float = 60.0, args: list[str] | None = None
) -> tuple[str, str, int, int]:
    """Run a step's script against the mount; return stdout, stderr, exit, ms."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code, mount, *(args or [])],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        return proc.stdout, proc.stderr, proc.returncode, duration_ms
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return out, "step timed out", 124, duration_ms


def execute(call: ToolCall, mount: str, timeout_s: float = 60.0) -> ToolResult:
    """Build + run one ToolCall on this host (the twin does exactly this).
    detonate/custom_script route through the sandbox (F7) instead."""
    if call.tool in (ToolName.detonate, ToolName.custom_script):
        # Local import avoids a module cycle: sandbox reuses valid_args from
        # this module before dispatching the isolated execution.
        from .sandbox import detonate, run_custom_script

        sandbox_fn = detonate if call.tool == ToolName.detonate else run_custom_script
        return sandbox_fn(call, mount, wall_s=timeout_s)
    code = build_code(call)
    stdout, stderr, exit_code, duration_ms = run_code(code, mount, timeout_s, step_argv(call))
    artifacts: list[Artifact] = []
    if call.tool == ToolName.extract and exit_code == 0:
        lines = stdout.splitlines()
        try:
            rel = next(l for l in lines if l.startswith("extracted "))[len("extracted "):]
            sha = next(l.split(" ", 1)[1] for l in lines if l.startswith("sha256 "))
            marker = next(
                i for i, l in enumerate(lines)
                if l.startswith("---- first ") and l.endswith(" chars ----")
            )
            excerpt = "\n".join(lines[marker + 1 :])
            artifacts.append(Artifact(path=rel, sha256=sha, excerpt=excerpt))
        except (StopIteration, ValueError, IndexError):
            pass  # malformed output: no artifact, analyst sees stdout
    return ToolResult(
        job_id=call.job_id,
        code=code,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        artifacts=artifacts,
    )
