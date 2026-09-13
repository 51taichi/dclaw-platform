# Super-expert capability parity

## Goal

A `super_expert` release inherits the same configured runtime tools and platform Skills as an ordinary Agent. Sealing continues to protect the signed package from console inspection, editing, export, and download. A normal `sealed_agent` package keeps the existing restricted runtime.

## Runtime policy

- Ordinary Agent: existing tool and MCP behavior.
- Normal sealed Agent: existing allowlist behavior.
- Super expert: ordinary built-in tools, configured plugin tools, and configured MCP tools. Agent-level enabled/disabled settings remain authoritative.
- All sealed runtimes keep prompts and packaged Skills under the release workspace and place task files in the separate sealed session directory.

## Platform Skill overlays

The global Skill inventory exposes a super expert as an installation target and shows only the Skills in its persistent per-Agent overlay. Packaged Skill metadata is never read through these APIs. Pool downloads write enabled Skills into that overlay outside signed release trees. Normal sealed Agents remain invalid targets.

At runtime the package Skills load first and the platform overlay loads second. A same-name overlay cannot replace a packaged Skill. The overlay path is stable across release upgrades, so platform-installed Skills remain available after a super-expert version changes.

## Security boundary

The existing sealed-asset API policy remains unchanged for inspection, editing, cloning, export, download, and trace endpoints. Direct file, media, presentation, and browser file operations resolve paths and reject any path, including symlink traversal, outside the per-session directory; sealed browser sessions also reject local `file://` navigation. Shell and Python subprocesses run under a Linux Landlock policy that grants write access only to that session directory and read/execute access only to required system runtime paths. It also denies creating symbolic links that could introduce a later path-swap escape. If Landlock is unavailable, these process tools fail closed. Dynamic Python package installation is disabled in sealed runtimes because installation would execute code outside the child sandbox. Package paths stay out of the model-facing workspace context.

Release activation and runtime reloads are serialized per Agent. Only the active release workspace can receive super-expert runtime permissions, and a failed activation restores the prior registry and runtime configuration. This change does not redefine a normal sealed package as a super expert.
