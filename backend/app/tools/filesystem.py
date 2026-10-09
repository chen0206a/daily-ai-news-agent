import os
import shlex
import shutil
import subprocess
from pathlib import Path
from ..security import SecurityError, Workspace


def list_dir(ws: Workspace, path="."):
    target = ws.path(path, directory=True)
    entries = []
    for p in sorted(target.iterdir()):
        if p.name.startswith("."):
            continue
        try:
            ws.path(p.relative_to(ws.root).as_posix(), directory=True)
        except SecurityError:
            continue
        entries.append({"name": p.name, "type": "directory" if p.is_dir() else "file"})
        if len(entries) >= 100:
            break
    return {"entries": entries}


def read_file(ws: Workspace, path):
    return {"path": path, "content": ws.read(path), "trust": "untrusted_file_data"}


def search_content(ws: Workspace, query, path="."):
    if not query or len(query) > 200:
        raise SecurityError("Query length must be 1–200")
    target = ws.path(path, directory=True)
    found = []
    # Do not recurse through symlinks or junctions, even while searching.
    stack = [target]
    visited = 0
    while stack and visited < 200:
        p = stack.pop()
        visited += 1
        if p.is_dir():
            for child in sorted(p.iterdir()):
                try:
                    ws.path(child.relative_to(ws.root).as_posix(), directory=True)
                except SecurityError:
                    continue
                stack.append(child)
        else:
            try:
                content = ws.read(p.relative_to(ws.root).as_posix())
            except (UnicodeError, SecurityError):
                continue
            for no, line in enumerate(content.splitlines(), 1):
                if query.casefold() in line.casefold():
                    found.append({"path": p.relative_to(ws.root).as_posix(), "line": no, "text": line[:300]})
                if len(found) >= 30:
                    return {"matches": found, "truncated": True}
    return {"matches": found, "truncated": bool(stack)}


def write_file(ws: Workspace, path, content):
    return ws.write(path, content)


def bash(ws: Workspace, command):
    """Execute a real allowlisted command as argv, NEVER through a shell interpreter."""
    if len(command) > 500 or any(c in command for c in ";&|><`$\n\r\x00"):
        raise SecurityError("Shell operators, substitutions and redirection are forbidden")
    args = shlex.split(command)
    if not args or args[0] not in {"pwd", "ls", "cat", "head", "wc"}:
        raise SecurityError("Allowed commands: pwd, ls, cat, head, wc")
    name = args[0]
    paths = args[1:]
    if any(p.startswith("-") for p in paths) or len(paths) > 1 or (name == "pwd" and paths):
        raise SecurityError("Flags and multiple paths are forbidden")
    if name in {"cat", "head", "wc"} and not paths:
        raise SecurityError("A file path is required")
    target = ws.path(paths[0] if paths else ".", directory=name in {"pwd", "ls"})
    binary = shutil.which(name)
    if os.name == "nt":
        # Git for Windows bundles real GNU utilities; do not resolve executables from a user workspace.
        candidates = [Path("C:/Program Files/Git/usr/bin") / f"{name}.exe"]
        git = shutil.which("git")
        if git:
            candidates.insert(0, Path(git).resolve().parents[1] / "usr" / "bin" / f"{name}.exe")
        binary = next((str(p) for p in candidates if p.is_file()), binary)
    if not binary or Path(binary).resolve().is_relative_to(ws.root.resolve()):
        raise SecurityError("Command unavailable; install coreutils / Git for Windows")
    argv = [binary]
    if name == "ls":
        argv += ["-1", "--", str(target)]
    elif name != "pwd":
        argv += ["--", str(target)]
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TMP", "TEMP") if k in os.environ}
    env.update({"LANG": "C.UTF-8", "HOME": str(ws.root)})
    result = subprocess.run(argv, cwd=ws.root, env=env, shell=False, capture_output=True, timeout=5)
    out = result.stdout.decode("utf-8", errors="replace").replace(str(ws.root), ".")
    return {"exit_code": result.returncode, "stdout": out[:16000],
            "stderr": result.stderr.decode("utf-8", errors="replace")[:1000], "truncated": len(out) > 16000}
