# -*- coding: utf-8 -*-
"""Python sandbox execution tool.

Provides a safe, isolated Python code execution environment for data analysis,
file generation, and computation tasks. Supports dynamic dependency installation
and returns execution results including generated files.
"""

import importlib.machinery
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import (
    get_current_tool_filesystem_root,
    get_current_workspace_dir,
)
from ...constant import WORKING_DIR
from .filesystem_sandbox import (
    ensure_landlock_available,
    landlock_preexec,
)


def _tool_error(msg: str) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {"ok": False, "error": msg},
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ],
    )


def _tool_ok(data: dict) -> ToolResponse:
    result = {"ok": True, **data}
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            ),
        ],
    )


def _looks_like_pptx_generation(code: str, description: str = "") -> bool:
    """Return True when sandbox code is trying to create a PPTX deck.

    Reading or inspecting an existing `.pptx` should remain allowed. The guard
    targets write/save operations so deck creation is routed through the
    dedicated presentation builder with media-usage QA.
    """
    haystack = f"{description}\n{code}".lower()
    if ".pptx" not in haystack:
        return False

    write_patterns = [
        r"\.save\s*\(\s*['\"][^'\"]+\.pptx",
        r"open\s*\(\s*['\"][^'\"]+\.pptx['\"]\s*,\s*['\"][^'\"]*w",
        r"zipfile\.zipfile\s*\(\s*['\"][^'\"]+\.pptx['\"]\s*,\s*['\"][^'\"]*w",
        r"writefile\s*\(\s*\{?\s*file(name)?\s*[:=]\s*['\"][^'\"]+\.pptx",
    ]
    if any(re.search(pattern, haystack) for pattern in write_patterns):
        return True

    python_pptx_imported = (
        "from pptx import" in haystack
        or "import pptx" in haystack
        or "presentation()" in haystack
    )
    return python_pptx_imported and ".save(" in haystack


def _install_packages(
    packages: list[str],
    *,
    target_dir: Path | None = None,
    workspace_dir: Path | None = None,
    preexec_fn: Callable[[], None] | None = None,
) -> tuple[bool, str]:
    """Install Python packages using pip.

    Returns (success, message) tuple.
    """
    if not packages:
        return True, ""

    # Filter out already installed packages. A session-local target is checked
    # without importing its code into the DClaw server process.
    to_install = []
    for pkg in packages:
        # Normalize package name for import check
        import_name = pkg.split("==")[0].split(">=")[0].split("<=")[0].strip()
        import_name = import_name.replace("-", "_").lower()
        if target_dir is not None:
            is_import_name = bool(
                re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", import_name),
            )
            if not is_import_name or importlib.machinery.PathFinder.find_spec(
                import_name,
                [str(target_dir)],
            ) is None:
                to_install.append(pkg)
        else:
            try:
                __import__(import_name)
            except ImportError:
                to_install.append(pkg)

    if not to_install:
        return True, "All packages already installed"

    try:
        command = [sys.executable, "-m", "pip", "install", "--quiet"]
        run_env = os.environ.copy()
        run_cwd = None
        if target_dir is not None:
            target_dir.mkdir(parents=True, exist_ok=True)
            command.extend(["--no-cache-dir", "--target", str(target_dir)])
        if workspace_dir is not None:
            runtime_dir = workspace_dir / ".python_runtime"
            temp_dir = runtime_dir / "tmp"
            home_dir = runtime_dir / "home"
            cache_dir = runtime_dir / "cache"
            for directory in (temp_dir, home_dir, cache_dir):
                directory.mkdir(parents=True, exist_ok=True)
            run_cwd = str(workspace_dir)
            run_env.update(
                {
                    "HOME": str(home_dir),
                    "TMPDIR": str(temp_dir),
                    "PIP_CACHE_DIR": str(cache_dir),
                    "XDG_CACHE_HOME": str(cache_dir),
                },
            )
        command.extend(to_install)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=run_cwd,
            env=run_env,
            preexec_fn=preexec_fn,
        )
        if result.returncode != 0:
            return False, f"pip install failed: {result.stderr}"
        return True, f"Successfully installed: {', '.join(to_install)}"
    except subprocess.TimeoutExpired:
        return False, "pip install timed out after 120 seconds"
    except Exception as e:
        return False, f"pip install error: {e!s}"


async def python_sandbox(
    code: str,
    install_packages: Optional[str] = None,
    timeout: float = 120.0,
    description: str = "",
) -> ToolResponse:
    """Execute Python code in a sandboxed environment.

    Use this tool when you need to run Python code for data analysis,
    file generation, computation, or any task that requires code execution.
    The code runs in the workspace directory and can access/create files there.

    **Features**:
    - Auto-install dependencies before execution
    - Access to workspace files for reading/writing
    - Returns stdout, generated files, and any errors
    - matplotlib plots are auto-saved as PNG files
    - PPTX generation is intentionally blocked; use `presentation_builder`
      for PowerPoint export so generated images are embedded and verified.

    Args:
        code (`str`):
            The Python code to execute. The code has access to the workspace
            directory via the `WORKSPACE_DIR` variable.
        install_packages (`str`, optional):
            Comma-separated list of pip packages to install before execution.
            Example: "pandas,matplotlib,openpyxl"
        timeout (`float`, defaults to 120.0):
            Maximum execution time in seconds.
        description (`str`, optional):
            Brief description of what the code does (for logging).

    Returns:
        `ToolResponse`:
            JSON with execution results including stdout output,
            any errors, execution time, and paths to generated files.
    """
    code = (code or "").strip()
    if not code:
        return _tool_error("code is required")
    if _looks_like_pptx_generation(code, description):
        return _tool_error(
            "PPTX generation through python_sandbox is blocked. "
            "Use the presentation_builder tool with structured slides, "
            "required_image_assets, and asset_usage_matrix so generated "
            "images are embedded and verified in the PPTX package.",
        )

    workspace_dir = get_current_workspace_dir() or WORKING_DIR
    workspace_dir = Path(workspace_dir).resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    filesystem_root = get_current_tool_filesystem_root()
    preexec_fn = None
    package_dir = None
    if filesystem_root is not None:
        filesystem_root = Path(filesystem_root).resolve()
        try:
            workspace_dir.relative_to(filesystem_root)
        except ValueError:
            return _tool_error(
                "Python workspace is outside the Agent session workspace",
            )
        try:
            ensure_landlock_available()
        except RuntimeError as exc:
            return _tool_error(str(exc))
        preexec_fn = landlock_preexec(filesystem_root)
        package_dir = workspace_dir / ".python_packages"

    # ── Install dependencies ──────────────────────────────────────────
    if install_packages:
        packages = [
            p.strip()
            for p in install_packages.split(",")
            if p.strip()
        ]
        if package_dir is None:
            success, msg = _install_packages(packages)
        else:
            success, msg = _install_packages(
                packages,
                target_dir=package_dir,
                workspace_dir=workspace_dir,
                preexec_fn=preexec_fn,
            )
        if not success:
            return _tool_error(f"Failed to install dependencies: {msg}")

    # ── Prepare execution script ──────────────────────────────────────
    # Inject workspace path and matplotlib backend config
    preamble = f"""
import os, sys
WORKSPACE_DIR = r"{workspace_dir}"
os.chdir(WORKSPACE_DIR)
{f'sys.path.insert(0, {str(package_dir)!r})' if package_dir else ''}
# Configure matplotlib for non-interactive backend
try:
    import matplotlib
    matplotlib.use("Agg")
except ImportError:
    pass
"""

    # Auto-save matplotlib figures
    postamble = """
try:
    import matplotlib.pyplot as plt
    figs = [plt.figure(n) for n in plt.get_fignums()]
    for i, fig in enumerate(figs):
        fig_path = os.path.join(WORKSPACE_DIR, f"plot_{int(__import__('time').time())}_{i}.png")
        fig.savefig(fig_path, dpi=150, bbox_inches="tight")
        print(f"[GENERATED_FILE] {fig_path}")
    plt.close("all")
except (ImportError, Exception):
    pass
"""

    full_code = preamble + "\n" + code + "\n" + postamble

    # ── Write to temp file and execute ────────────────────────────────
    script_fd, script_path = tempfile.mkstemp(
        suffix=".py",
        prefix="sandbox_",
        dir=str(workspace_dir),
    )

    try:
        with os.fdopen(script_fd, "w", encoding="utf-8") as f:
            f.write(full_code)

        start_time = time.time()

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace_dir),
            check=False,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": os.pathsep.join(
                    str(path)
                    for path in (package_dir, workspace_dir)
                    if path is not None
                ),
            },
            preexec_fn=preexec_fn,
        )

        elapsed = round(time.time() - start_time, 2)
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        # Extract generated file paths
        generated_files = []
        output_lines = []
        for line in stdout.split("\n"):
            if line.startswith("[GENERATED_FILE] "):
                generated_files.append(line[17:].strip())
            else:
                output_lines.append(line)

        clean_stdout = "\n".join(output_lines).strip()

        # Truncate long output
        max_output = 8000
        if len(clean_stdout) > max_output:
            clean_stdout = (
                clean_stdout[:max_output]
                + f"\n... (output truncated, {len(clean_stdout)} chars total)"
            )

        response_data = {
            "action": "execute",
            "exit_code": result.returncode,
            "execution_time_seconds": elapsed,
        }

        if clean_stdout:
            response_data["stdout"] = clean_stdout
        if stderr and result.returncode != 0:
            # Only include stderr on failure
            if len(stderr) > 4000:
                stderr = stderr[-4000:]
            response_data["stderr"] = stderr
        if generated_files:
            response_data["generated_files"] = generated_files

        if result.returncode == 0:
            response_data["message"] = (
                f"Code executed successfully in {elapsed}s"
            )
        else:
            response_data["message"] = (
                f"Code execution failed (exit code {result.returncode})"
            )

        return _tool_ok(response_data)

    except subprocess.TimeoutExpired:
        return _tool_error(
            f"Code execution timed out after {timeout} seconds. "
            f"Consider optimizing the code or increasing the timeout."
        )
    except Exception as e:
        return _tool_error(f"Sandbox execution error: {e!s}")
    finally:
        # Clean up temp script
        try:
            os.unlink(script_path)
        except OSError:
            pass
