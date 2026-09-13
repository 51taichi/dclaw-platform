# Super-expert capability parity implementation plan

1. Add registry-level active package classification for super experts.
2. Add failing tests for built-in/plugin/MCP parity and keep normal sealed restrictions.
3. Make super-expert runtime tool registration follow ordinary Agent policy.
4. Add failing tests for Skill inventory targets and sealed download authorization.
5. Allow platform Skill installation into a persistent super-expert overlay without exposing packaged Skill metadata.
6. Load platform-added Skills from a persistent per-Agent overlay independent of signed releases.
7. Confine file, Shell, and Python tools to the sealed session workspace, failing closed when Linux Landlock is unavailable.
8. Run focused and broader server tests, review the diff, commit, and push `main`.
