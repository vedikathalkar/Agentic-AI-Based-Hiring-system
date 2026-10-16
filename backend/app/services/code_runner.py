"""Sandboxed execution of candidate code.

Candidate code NEVER runs inside the FastAPI process. Two backends:

* ``docker`` (recommended for production, CODE_RUNNER=docker): each compile/run
  happens in a throw-away container with ``--network none``, memory/CPU/pids
  limits, a read-only root filesystem and a tmpfs work dir.
* ``local`` (default on Linux/macOS): a separate process in a fresh temp dir with
  POSIX rlimits (CPU seconds, address space, file size, open files), its own
  process group (killed on timeout), a stripped environment and — when the
  kernel allows unprivileged namespaces — no network (``unshare -rn``).

On platforms without either (e.g. Windows without Docker) no language is
reported as available, so the UI never offers something that cannot run.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)
MAX_OUTPUT = 64 * 1024

LANGUAGES = {
    "python": {"label": "Python 3", "file": "main.py", "docker_image": "python:3.11-slim",
               "compile": None, "run": ["{python}", "-I", "-B", "main.py"]},
    "java": {"label": "Java", "file": "Main.java", "docker_image": "eclipse-temurin:17-jdk",
             "compile": ["javac", "-J-Xmx256m", "Main.java"], "run": ["java", "-Xmx{mem}m", "-Xss64m", "-XX:+UseSerialGC", "Main"]},
    "cpp": {"label": "C++17", "file": "main.cpp", "docker_image": "gcc:13",
            "compile": ["g++", "-O2", "-std=c++17", "-o", "main", "main.cpp"],
            "run": ["main.exe" if os.name == "nt" else "./main"]},
}

STARTER_CODE = {
    "python": "import sys\n\ndef main():\n    data = sys.stdin.read().split()\n    # write your solution here\n\nif __name__ == \"__main__\":\n    main()\n",
    "java": "import java.util.*;\nimport java.io.*;\n\npublic class Main {\n    public static void main(String[] args) throws IOException {\n        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));\n        // write your solution here\n    }\n}\n",
    "cpp": "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    // write your solution here\n    return 0;\n}\n",
}


@dataclass
class RunResult:
    status: str                    # ok | runtime_error | time_limit | memory_limit | output_limit
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    time_ms: int = 0
    memory_kb: Optional[int] = None


@dataclass
class TestOutcome:
    passed: bool
    status: str
    time_ms: int
    memory_kb: Optional[int]
    input: Optional[str] = None
    expected: Optional[str] = None
    actual: Optional[str] = None
    stderr: Optional[str] = None


@dataclass
class ExecutionReport:
    status: str   # accepted | wrong_answer | compile_error | runtime_error | time_limit | memory_limit | error
    passed: int = 0
    total: int = 0
    time_ms: int = 0
    memory_kb: Optional[int] = None
    error: Optional[str] = None
    tests: list[TestOutcome] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round(self.passed / self.total * 100, 1) if self.total else 0.0


def runner_mode() -> str:
    mode = (os.getenv("CODE_RUNNER") or "").strip().lower()
    if mode in ("docker", "local", "disabled"):
        return mode
    if os.name == "posix":
        return "local"
    # Windows/dev machines: prefer Docker isolation, otherwise run locally with timeouts only.
    return "docker" if _docker_available() else "local"


@lru_cache(maxsize=1)
def _network_isolation_available() -> bool:
    if os.name != "posix" or not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def _mount_isolation_available() -> bool:
    if not _network_isolation_available():
        return False
    try:
        return subprocess.run(["unshare", "-rnm", "--propagation", "private", "sh", "-c",
                               "mount -t tmpfs tmpfs /tmp"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def _hidden_paths() -> tuple[list[str], list[str]]:
    """Secrets/data the candidate process must not be able to read in local mode:
    (files to mask with /dev/null, directories to cover with an empty tmpfs)."""
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    files = [os.path.join(backend, ".env"), os.path.join(os.path.dirname(backend), ".env")]
    dirs = [os.path.join(backend, "storage"), os.path.join(backend, "uploads")]
    try:
        from ..database import SQLALCHEMY_DATABASE_URL
        if SQLALCHEMY_DATABASE_URL.startswith("sqlite:///"):
            files.append(SQLALCHEMY_DATABASE_URL[len("sqlite:///"):])
    except Exception:
        pass
    store = os.getenv("STORAGE_DIR")
    if store:
        dirs.append(store if os.path.isabs(store) else os.path.join(backend, store))
    return [f for f in files if os.path.isfile(f)], [d for d in dirs if os.path.isdir(d)]


def sandbox_info() -> dict:
    mode = runner_mode()
    return {"mode": mode,
            "network_isolated": mode == "docker" or (mode == "local" and _network_isolation_available()),
            "secrets_hidden": mode == "docker" or (mode == "local" and _mount_isolation_available()),
            "production_ready": mode == "docker" and _docker_available()}


@lru_cache(maxsize=1)
def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def available_languages() -> list[dict]:
    mode = runner_mode()
    out = []
    for key, spec in LANGUAGES.items():
        if mode == "docker":
            ok = _docker_available()
        elif mode == "local":
            if key == "python":
                ok = bool(sys.executable)
            elif key == "java":
                ok = bool(shutil.which("javac") and shutil.which("java"))
            else:
                ok = bool(shutil.which("g++"))
        else:
            ok = False
        if ok:
            out.append({"key": key, "label": spec["label"], "starter": STARTER_CODE[key]})
    return out


def is_available(language: str) -> bool:
    return any(lang["key"] == language for lang in available_languages())


def _normalize(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").strip().split("\n")]
    return "\n".join(lines)


def _limits(cpu_seconds: int, memory_mb: Optional[int]):
    def apply():  # runs in the child between fork and exec
        import resource
        os.setsid()
        limits = [(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1)),
                  (resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024)),
                  (resource.RLIMIT_NOFILE, (256, 256)),
                  (resource.RLIMIT_CORE, (0, 0))]
        if memory_mb:
            limits.append((resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2))
        for which, value in limits:
            try:   # some limits are unsupported (e.g. RLIMIT_AS on macOS); the wall-clock timer still applies
                resource.setrlimit(which, value)
            except (ValueError, OSError):
                pass
    return apply


def _exec(cmd: list[str], cwd: str, stdin: str, timeout_s: float, memory_mb: Optional[int]) -> RunResult:
    """Run one command in a separate, limited process and collect rusage."""
    # Minimal environment: the server's PATH (so compilers are found) but none of its secrets.
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": cwd, "LANG": "C.UTF-8",
           "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt":
        env.update({k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP") if k in os.environ})
    if os.name == "nt" and os.path.isfile(os.path.join(cwd, cmd[0])):
        cmd = [os.path.join(cwd, cmd[0]), *cmd[1:]]   # Windows resolves relative programs against our CWD, not cwd=
    if runner_mode() == "local" and _mount_isolation_available():
        files, dirs = _hidden_paths()
        script = "".join(f'mount --bind /dev/null "{f}" || exit 97; ' for f in files)
        script += "".join(f'mount -t tmpfs tmpfs "{d}" || exit 97; ' for d in dirs)
        cmd = ["unshare", "-rnm", "--propagation", "private", "sh", "-c", script + 'exec "$@"', "sandbox", *cmd]
    elif runner_mode() == "local" and _network_isolation_available():
        cmd = ["unshare", "-rn", *cmd]
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        preexec_fn=_limits(int(timeout_s) + 1, memory_mb) if os.name == "posix" and runner_mode() == "local" else None,
        start_new_session=os.name == "posix" and runner_mode() != "local",
    )
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    overflow = {"hit": False}

    def pump(stream, sink):
        total = 0
        while True:
            chunk = stream.read(8192)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_OUTPUT:
                overflow["hit"] = True
                _kill(proc)
                break
            sink.append(chunk)

    def feed():
        try:
            proc.stdin.write((stdin or "").encode())
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threads = [threading.Thread(target=feed, daemon=True),
               threading.Thread(target=pump, args=(proc.stdout, out_chunks), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err_chunks), daemon=True)]
    for t in threads:
        t.start()
    timed_out = {"hit": False}

    def on_timeout():
        timed_out["hit"] = True
        _kill(proc)
    timer = threading.Timer(timeout_s, on_timeout)
    timer.start()
    memory_kb = None
    try:
        if os.name == "posix":
            _, status, usage = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
            memory_kb = int(usage.ru_maxrss) if sys.platform != "darwin" else int(usage.ru_maxrss / 1024)
        else:
            proc.wait()
    finally:
        timer.cancel()
    for t in threads[1:]:
        t.join(timeout=2)
    elapsed = int((time.monotonic() - started) * 1000)
    stdout = b"".join(out_chunks).decode("utf-8", "replace")
    stderr = b"".join(err_chunks).decode("utf-8", "replace")[-4000:]
    code = proc.returncode
    xcpu = os.name == "posix" and code in (-signal.SIGXCPU, 128 + signal.SIGXCPU)
    if code == 97 and not stdout and runner_mode() == "local":
        status = "runtime_error"
        stderr = "Sandbox setup failed"
    elif timed_out["hit"] or xcpu:
        status = "time_limit"
    elif overflow["hit"]:
        status = "output_limit"
    elif code != 0 and ("MemoryError" in stderr or "OutOfMemoryError" in stderr or "bad_alloc" in stderr
                        or code in (137, -9) and memory_kb and memory_mb and memory_kb >= memory_mb * 1024 * 0.9):
        status = "memory_limit"
    elif code != 0:
        status = "runtime_error"
    else:
        status = "ok"
    return RunResult(status, stdout, stderr, code, elapsed, memory_kb)


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _docker_cmd(language: str, workdir: str, inner: list[str], memory_mb: int, writable: bool) -> list[str]:
    spec = LANGUAGES[language]
    return ["docker", "run", "--rm", "-i", "--network", "none", "--memory", f"{memory_mb}m",
            "--memory-swap", f"{memory_mb}m", "--cpus", "1", "--pids-limit", "64", "--read-only",
            "--tmpfs", "/tmp:rw,size=64m", "--security-opt", "no-new-privileges", "--cap-drop", "ALL",
            "-u", "65534:65534", "-v", f"{workdir}:/code:{'rw' if writable else 'ro'}", "-w", "/code",
            spec["docker_image"], *inner]


def execute(language: str, source: str, tests: list[dict], time_limit_ms: int = 2000,
            memory_limit_mb: int = 256, stop_on_compile_error: bool = True) -> ExecutionReport:
    """Compile once, run every test case, compare normalized stdout."""
    if language not in LANGUAGES:
        return ExecutionReport("error", error=f"Unsupported language: {language}")
    if not is_available(language):
        return ExecutionReport("error", error=f"{LANGUAGES[language]['label']} is not available on this server")
    if len(source or "") > 100_000:
        return ExecutionReport("error", error="Source code is too large (100 KB max)")
    spec = LANGUAGES[language]
    mode = runner_mode()
    workdir = tempfile.mkdtemp(prefix="hirelune-run-")
    try:
        os.chmod(workdir, 0o777)
        with open(os.path.join(workdir, spec["file"]), "w", encoding="utf-8") as f:
            f.write(source or "")
        if spec["compile"]:
            cmd = spec["compile"]
            cmd = _docker_cmd(language, workdir, cmd, 512, True) if mode == "docker" else cmd
            res = _exec(cmd, workdir, "", 20.0 if mode == "local" else 60.0, None if language == "java" else 1024)
            if res.status != "ok":
                msg = (res.stderr or res.stdout or "Compilation failed").strip()
                if res.status == "time_limit":
                    msg = "Compilation timed out"
                return ExecutionReport("compile_error", total=len(tests), error=msg[-4000:])
        # Java's JVM reserves far more virtual memory than it uses, so heap
        # limits are enforced with -Xmx instead of RLIMIT_AS.
        run_mem = None if language == "java" else memory_limit_mb + (64 if language == "python" else 16)
        run_cmd = [part.format(python=sys.executable, mem=memory_limit_mb) for part in spec["run"]]
        if mode == "docker":
            run_cmd = [("python3" if p == sys.executable else p) for p in run_cmd]
            run_cmd = _docker_cmd(language, workdir, run_cmd, memory_limit_mb + 64, False)
        timeout = time_limit_ms / 1000 + (1.5 if language == "java" else 0.25) + (2.0 if mode == "docker" else 0)
        report = ExecutionReport("accepted", total=len(tests))
        worst = None
        for i, test in enumerate(tests):
            if worst == "time_limit":
                # Don't burn minutes of CPU on a solution that already timed out.
                report.tests.append(TestOutcome(False, "skipped", 0, None, test.get("input"),
                                                _normalize(str(test.get("output", ""))), None, None))
                continue
            res = _exec(run_cmd, workdir, test.get("input", ""), timeout, run_mem)
            expected = _normalize(str(test.get("output", "")))
            actual = _normalize(res.stdout)
            passed = res.status == "ok" and actual == expected
            status = "passed" if passed else ("wrong_answer" if res.status == "ok" else res.status)
            report.tests.append(TestOutcome(passed, status, res.time_ms, res.memory_kb, test.get("input"),
                                            expected, actual[:2000], (res.stderr or "")[-1000:] or None))
            report.passed += int(passed)
            report.time_ms = max(report.time_ms, res.time_ms)
            if res.memory_kb:
                report.memory_kb = max(report.memory_kb or 0, res.memory_kb)
            if not passed and worst is None:
                worst = status
        first_err = next((t.stderr for t in report.tests if t.stderr), "") or ""
        if language == "python" and report.passed == 0 and re.search(r"^(SyntaxError|IndentationError|TabError)\b", first_err, re.M):
            # Python has no separate compile step; surface syntax errors as compile errors.
            report.status, report.error = "compile_error", first_err[-4000:]
            return report
        if report.passed != report.total:
            report.status = worst if worst in ("runtime_error", "time_limit", "memory_limit") else "wrong_answer"
            if report.status == "output_limit":
                report.status = "runtime_error"
        return report
    except Exception:  # noqa: BLE001
        logger.exception("Code execution failed (%s)", language)
        return ExecutionReport("error", total=len(tests), error="The code runner failed unexpectedly. Please try again.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
