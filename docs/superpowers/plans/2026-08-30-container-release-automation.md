# DClaw Combined Image Release Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one auditable combined server/client image in GHCR and let the existing Alibaba Cloud production installation update or roll back safely with one command.

**Architecture:** GitHub Actions in `dclaw-server` resolves an immutable `(server_sha, client_sha)` pair, assembles the client Console and docs into the server Docker context, verifies the image labels, publishes the immutable tag, and only then advances `main`. A lightweight `dclaw-client` workflow dispatches client-main changes to the server workflow. Production uses a Compose project that owns only the `dclaw` application container and shell tooling that preserves the existing PostgreSQL, Redis, network, volumes, port, domain, backups, and rollback images.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, Docker Compose v2, POSIX shell/Bash, Python 3.11, pytest, PyYAML, FastAPI `/api/version` health endpoint.

**Spec:** `docs/superpowers/specs/2026-08-30-container-release-automation-design.md`

## Global Constraints

- Keep `51taichi/dclaw-server` and `51taichi/dclaw-client` as separate repositories.
- Publish one combined image at `ghcr.io/51taichi/dclaw` with immutable labels `cn.deepmega.dclaw.server-revision` and `cn.deepmega.dclaw.client-revision`.
- Production continues to run one application container named `dclaw` on `127.0.0.1:18088:8088` with restart policy `unless-stopped`.
- Production Compose must not manage, recreate, delete, or rename `dclaw-postgres`, `dclaw-redis`, `dclaw-net`, `dclaw-data`, `dclaw-secrets`, or `dclaw-backups`.
- The only normal production update entry point is `/opt/dclaw-deploy/update.sh`; server-only, client-only, and combined changes use the same command.
- Default updates discover `ghcr.io/51taichi/dclaw:main`; exact updates require full 40-character server and client SHAs and a matching immutable image label pair.
- Health checks allow 420 seconds because the current production image has demonstrated approximately 282-second startup.
- Every update creates and validates a PostgreSQL custom-format dump before stopping or recreating the application container.
- Ordinary rollback changes only the application image; it never restores the database automatically.
- Secrets must enter `docker login` through stdin, deployment files are mode `0600`, and status/log output must not expose environment values, database URLs, authorization headers, or secret-volume contents.
- Do not run `docker system prune` or automatically delete historical images, rollback containers, dumps, or volumes.
- GitHub pushes build artifacts but never modify production without an explicit server-side command.
- Use TDD for every behavior change and preserve unrelated existing release workflows unless a test proves they conflict.

---

## File Map

### `dclaw-server`

- `.github/workflows/dclaw-combined-image.yml`: resolve the two immutable SHAs, build/test the combined context, publish the immutable tag, and finally advance `main`.
- `scripts/release/resolve_release.py`: pure event/manual-input SHA resolution and validation used by CI and unit tests.
- `scripts/release/assemble_context.sh`: verify exact checkouts and inject `client/console` plus `client/website/public/docs` into a copied server build context.
- `deploy/production/compose.production.yml`: app-only Compose definition using existing external resources.
- `deploy/production/lib.sh`: shared lock, image inspection, backup, health, manifest, and redaction-safe helpers.
- `deploy/production/update.sh`: no-op detection and guarded image update with automatic image rollback.
- `deploy/production/status.sh`: read-only deployment status without secret disclosure.
- `deploy/production/rollback.sh`: switch to the last immutable successful image using the shared lock and health gate.
- `deploy/production/adopt.sh`: one-time conversion of the current hand-created `dclaw` container into the Compose-managed container.
- `deploy/production/production.env.example`: non-secret key names and documented values; never real credentials.
- `tests/unit/release/test_release_resolution.py`: SHA/event resolution tests.
- `tests/unit/release/test_combined_workflow.py`: workflow trigger, ordering, permissions, tags, and label contract tests.
- `tests/unit/release/test_build_context.py`: checkout/content/build-failure contract tests with temporary Git trees and fake commands.
- `tests/unit/release/test_production_compose.py`: rendered Compose ownership/resource assertions.
- `tests/unit/release/test_production_scripts.py`: fake-Docker update/status/rollback/adoption failure-matrix tests.
- `docs/operations/dclaw-container-release.md`: GitHub secret setup, server installation, normal update/status/rollback, logs, and disaster-recovery boundary.

### `dclaw-client`

- `.github/workflows/dispatch-dclaw-server-image.yml`: dispatch immutable `client_sha` after a successful client `main` push and support manual redispatch.
- `console/src/release/dispatchContract.test.ts`: static workflow contract test invoked by the client test job.

---

### Task 1: Immutable Release Pair Resolver and Context Assembler

**Files:**
- Create: `scripts/release/resolve_release.py`
- Create: `scripts/release/assemble_context.sh`
- Create: `tests/unit/release/__init__.py`
- Create: `tests/unit/release/test_release_resolution.py`
- Create: `tests/unit/release/test_build_context.py`

**Interfaces:**
- Produces: `resolve_pair(event_name: str, event_payload: Mapping[str, Any], inputs: Mapping[str, str], server_main_sha: str, client_main_sha: str) -> ReleasePair`.
- Produces: immutable `ReleasePair(server_sha: str, client_sha: str)` with `pair_tag == server-<12>-client-<12>`.
- Produces: `assemble_context.sh SERVER_DIR CLIENT_DIR OUTPUT_DIR SERVER_SHA CLIENT_SHA`, which exits nonzero without changing a pre-existing output when validation fails.
- Consumes: standard Git, `npm ci`, and `npm run build`; no GitHub-only runtime is required for local tests.

- [ ] **Step 1: Write resolver RED tests**

```python
def test_client_dispatch_uses_payload_sha_and_current_server_main() -> None:
    pair = resolve_pair(
        "repository_dispatch",
        {"action": "dclaw_client_main", "client_payload": {"client_sha": "b" * 40}},
        {},
        server_main_sha="a" * 40,
        client_main_sha="c" * 40,
    )
    assert pair == ReleasePair(server_sha="a" * 40, client_sha="b" * 40)
    assert pair.pair_tag == f"server-{'a' * 12}-client-{'b' * 12}"


@pytest.mark.parametrize("bad", ["main", "abc", "g" * 40, "a" * 39])
def test_rejects_non_full_git_sha(bad: str) -> None:
    with pytest.raises(ValueError, match="40-character lowercase hexadecimal SHA"):
        ReleasePair(server_sha=bad, client_sha="b" * 40)
```

- [ ] **Step 2: Run resolver tests and preserve the failure**

Run: `.venv/bin/python -m pytest tests/unit/release/test_release_resolution.py -q`

Expected: FAIL during import because `scripts.release.resolve_release` does not exist.

- [ ] **Step 3: Implement the resolver as a pure module and CLI**

```python
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ReleasePair:
    server_sha: str
    client_sha: str

    def __post_init__(self) -> None:
        for value in (self.server_sha, self.client_sha):
            if not SHA_RE.fullmatch(value):
                raise ValueError("revision must be a 40-character lowercase hexadecimal SHA")

    @property
    def pair_tag(self) -> str:
        return f"server-{self.server_sha[:12]}-client-{self.client_sha[:12]}"
```

The CLI must emit only `server_sha=…`, `client_sha=…`, and `pair_tag=…` lines to `$GITHUB_OUTPUT`; it must never print token values or event payload wholesale.

- [ ] **Step 4: Write context-assembly RED tests**

```python
def test_assembler_rejects_missing_client_docs(tmp_path: Path) -> None:
    server, client = make_git_inputs(tmp_path, include_docs=False)
    result = run_assembler(server, client, tmp_path / "out")
    assert result.returncode != 0
    assert "website/public/docs" in result.stderr
    assert not (tmp_path / "out").exists()


def test_assembler_rejects_head_mismatch(tmp_path: Path) -> None:
    server, client = make_git_inputs(tmp_path)
    result = run_assembler(server, client, tmp_path / "out", server_sha="0" * 40)
    assert result.returncode != 0
    assert "server HEAD does not match" in result.stderr
```

- [ ] **Step 5: Run assembler tests and preserve the failure**

Run: `.venv/bin/python -m pytest tests/unit/release/test_build_context.py -q`

Expected: FAIL because `scripts/release/assemble_context.sh` is absent.

- [ ] **Step 6: Implement atomic context assembly**

```bash
actual_server=$(git -C "$SERVER_DIR" rev-parse HEAD)
actual_client=$(git -C "$CLIENT_DIR" rev-parse HEAD)
test "$actual_server" = "$SERVER_SHA" || fail "server HEAD does not match"
test "$actual_client" = "$CLIENT_SHA" || fail "client HEAD does not match"
test -f "$SERVER_DIR/deploy/Dockerfile" || fail "deploy/Dockerfile is missing"
test -f "$CLIENT_DIR/console/package-lock.json" || fail "console/package-lock.json is missing"
test -d "$CLIENT_DIR/website/public/docs" || fail "website/public/docs is missing"

tmp_output=$(mktemp -d "${OUTPUT_DIR}.tmp.XXXXXX")
trap 'rm -rf "$tmp_output"' EXIT
git -C "$SERVER_DIR" archive "$SERVER_SHA" | tar -x -C "$tmp_output"
mkdir -p "$tmp_output/console" "$tmp_output/website/public/docs"
git -C "$CLIENT_DIR" archive "$CLIENT_SHA" console | tar -x --strip-components=1 -C "$tmp_output/console"
git -C "$CLIENT_DIR" archive "$CLIENT_SHA" website/public/docs | tar -x -C "$tmp_output"
mv "$tmp_output" "$OUTPUT_DIR"
trap - EXIT
```

Run `npm ci --include=dev` and `npm run build` against the assembled `console` before declaring the context valid; propagate either failure unchanged.

- [ ] **Step 7: Run all Task 1 tests and commit**

Run: `.venv/bin/python -m pytest tests/unit/release/test_release_resolution.py tests/unit/release/test_build_context.py -q`

Expected: PASS.

```bash
git add scripts/release tests/unit/release
git commit -m "feat: assemble immutable DClaw release inputs"
```

---

### Task 2: Server Combined-Image GHCR Workflow

**Files:**
- Create: `.github/workflows/dclaw-combined-image.yml`
- Create: `tests/unit/release/test_combined_workflow.py`
- Modify: `tests/unit/release/test_build_context.py`

**Interfaces:**
- Consumes: `resolve_release.py` CLI and `assemble_context.sh` from Task 1.
- Produces: `ghcr.io/51taichi/dclaw:server-<12>-client-<12>` and, only after verification, `ghcr.io/51taichi/dclaw:main`.
- Accepts: `push` on server `main`, `repository_dispatch` type `dclaw_client_main`, and `workflow_dispatch` optional full `server_sha`/`client_sha`.

- [ ] **Step 1: Write workflow RED tests**

```python
def test_combined_workflow_has_all_three_entry_points() -> None:
    workflow = load_workflow(".github/workflows/dclaw-combined-image.yml")
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["on"]["repository_dispatch"]["types"] == ["dclaw_client_main"]
    assert "workflow_dispatch" in workflow["on"]


def test_main_is_published_only_after_immutable_image_verification() -> None:
    steps = workflow_steps()
    assert step_index(steps, "verify-image-labels") < step_index(steps, "publish-main-tag")
    assert "cn.deepmega.dclaw.server-revision" in step_script(steps, "verify-image-labels")
    assert "cn.deepmega.dclaw.client-revision" in step_script(steps, "verify-image-labels")
```

- [ ] **Step 2: Run and preserve RED**

Run: `.venv/bin/python -m pytest tests/unit/release/test_combined_workflow.py -q`

Expected: FAIL because the workflow file is absent.

- [ ] **Step 3: Implement the workflow with minimal permissions and exact checkouts**

```yaml
name: DClaw Combined Image
on:
  push:
    branches: [main]
  repository_dispatch:
    types: [dclaw_client_main]
  workflow_dispatch:
    inputs:
      server_sha:
        required: false
        type: string
      client_sha:
        required: false
        type: string
permissions:
  contents: read
  packages: write
concurrency:
  group: dclaw-combined-${{ github.event_name }}-${{ github.ref || github.event.client_payload.client_sha }}
  cancel-in-progress: true
```

The job must resolve branch tips before calling the pure resolver, checkout both exact SHAs, assemble/test the context, build the immutable tag, pull and inspect it, compare both full labels, and only then retag/push `main`. Use `secrets.DCLAW_CLIENT_READ_TOKEN` only for the private client checkout and `GITHUB_TOKEN` for GHCR login.

- [ ] **Step 4: Add failure-path contract tests**

```python
def test_workflow_never_pushes_main_in_build_step() -> None:
    build = step_script(workflow_steps(), "build-immutable-image")
    assert ":main" not in build


def test_workflow_uses_read_token_only_for_client_checkout() -> None:
    server = step(workflow_steps(), "checkout-server")
    client = step(workflow_steps(), "checkout-client")
    assert "DCLAW_CLIENT_READ_TOKEN" not in json.dumps(server)
    assert "DCLAW_CLIENT_READ_TOKEN" in json.dumps(client)
```

- [ ] **Step 5: Run workflow/context tests and commit**

Run: `.venv/bin/python -m pytest tests/unit/release/test_combined_workflow.py tests/unit/release/test_build_context.py -q`

Expected: PASS.

```bash
git add .github/workflows/dclaw-combined-image.yml tests/unit/release
git commit -m "ci: publish combined DClaw images to GHCR"
```

---

### Task 3: Client Main Dispatch Workflow

**Files (`dclaw-client` repository):**
- Create: `.github/workflows/dispatch-dclaw-server-image.yml`
- Create: `console/src/release/dispatchContract.test.ts`

**Interfaces:**
- Produces: GitHub `repository_dispatch` to `51taichi/dclaw-server` with event type `dclaw_client_main` and payload `{ "client_sha": "${{ github.sha }}" }`.
- Consumes: client secret `DCLAW_SERVER_DISPATCH_TOKEN` with permission only to dispatch the server repository.

- [ ] **Step 1: Create an isolated client worktree**

```bash
git -C "/Users/moxi/Desktop/codex space/dclaw-client" fetch origin main
git -C "/Users/moxi/Desktop/codex space/dclaw-client" worktree add \
  "/Users/moxi/Desktop/codex space/dclaw-client/.worktrees/container-release-dispatch" \
  -b codex/container-release-dispatch origin/main
```

- [ ] **Step 2: Write the client workflow RED test**

```ts
it("dispatches the immutable client main SHA to dclaw-server", () => {
  const workflow = readFileSync(workflowPath, "utf8");
  expect(workflow).toContain("types: [dclaw_client_main]");
  expect(workflow).toContain('client_sha: "${{ github.sha }}"');
  expect(workflow).toContain("DCLAW_SERVER_DISPATCH_TOKEN");
  expect(workflow).not.toContain("docker build");
});
```

- [ ] **Step 3: Run and preserve RED**

Run: `npm --prefix console test -- dispatchContract.test.ts --run`

Expected: FAIL because the workflow is absent.

- [ ] **Step 4: Implement push/manual dispatch**

```yaml
name: Request DClaw Combined Image
on:
  push:
    branches: [main]
  workflow_dispatch: {}
permissions:
  contents: read
jobs:
  dispatch:
    runs-on: ubuntu-latest
    steps:
      - name: Dispatch immutable client revision
        env:
          GH_TOKEN: ${{ secrets.DCLAW_SERVER_DISPATCH_TOKEN }}
        run: >-
          gh api --method POST repos/51taichi/dclaw-server/dispatches
          -f event_type=dclaw_client_main
          -f 'client_payload[client_sha]=${{ github.sha }}'
```

- [ ] **Step 5: Run client tests and commit without pushing**

Run: `npm --prefix console test -- dispatchContract.test.ts --run && npm --prefix console run lint`

Expected: PASS.

```bash
git add .github/workflows/dispatch-dclaw-server-image.yml console/src/release/dispatchContract.test.ts
git commit -m "ci: dispatch client releases to server image build"
```

Do not push either repository until Task 8 verifies the two workflows together and the user explicitly authorizes the push.

---

### Task 4: App-Only Production Compose Contract

**Files:**
- Create: `deploy/production/compose.production.yml`
- Create: `deploy/production/production.env.example`
- Create: `tests/unit/release/test_production_compose.py`

**Interfaces:**
- Consumes: `DCLAW_IMAGE` from `/opt/dclaw-deploy/release.env` and application variables from `/opt/dclaw-deploy/production.env`.
- Produces: Compose project `dclaw-production` with exactly one service and three external volumes plus one external network.

- [ ] **Step 1: Write Compose RED tests**

```python
def test_production_compose_owns_only_application_container() -> None:
    rendered = render_compose(DCLAW_IMAGE="ghcr.io/51taichi/dclaw@sha256:" + "a" * 64)
    assert set(rendered["services"]) == {"dclaw"}
    app = rendered["services"]["dclaw"]
    assert app["container_name"] == "dclaw"
    assert app["ports"] == ["127.0.0.1:18088:8088"]
    assert app["restart"] == "unless-stopped"


def test_all_runtime_resources_are_external() -> None:
    rendered = render_compose()
    assert rendered["networks"]["dclaw-net"] == {"external": True, "name": "dclaw-net"}
    assert all(value["external"] is True for value in rendered["volumes"].values())
```

- [ ] **Step 2: Run and preserve RED**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_compose.py -q`

Expected: FAIL because the Compose template is absent.

- [ ] **Step 3: Implement the exact app-only Compose file**

```yaml
services:
  dclaw:
    image: ${DCLAW_IMAGE:?DCLAW_IMAGE is required}
    container_name: dclaw
    restart: unless-stopped
    env_file:
      - ./production.env
    ports:
      - 127.0.0.1:18088:8088
    volumes:
      - dclaw-data:/app/working
      - dclaw-secrets:/app/working.secret
      - dclaw-backups:/app/working.backups
    networks: [dclaw-net]
networks:
  dclaw-net:
    external: true
    name: dclaw-net
volumes:
  dclaw-data: {external: true, name: dclaw-data}
  dclaw-secrets: {external: true, name: dclaw-secrets}
  dclaw-backups: {external: true, name: dclaw-backups}
```

- [ ] **Step 4: Add rejection tests for forbidden ownership and secret examples**

```python
def test_compose_does_not_define_database_or_redis() -> None:
    text = COMPOSE.read_text()
    assert "dclaw-postgres:" not in text
    assert "dclaw-redis:" not in text


def test_example_env_contains_no_credentials() -> None:
    text = EXAMPLE_ENV.read_text()
    assert "postgresql+" not in text
    assert "TOKEN=" not in text
    assert "PASSWORD=" not in text
```

- [ ] **Step 5: Render twice and commit**

Run: `DCLAW_IMAGE=ghcr.io/51taichi/dclaw@sha256:$(printf 'a%.0s' {1..64}) docker compose -f deploy/production/compose.production.yml --env-file deploy/production/production.env.example config >/tmp/dclaw-compose.yml`

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_compose.py -q`

Expected: both PASS.

```bash
git add deploy/production/compose.production.yml deploy/production/production.env.example tests/unit/release/test_production_compose.py
git commit -m "feat: define app-only DClaw production compose"
```

---

### Task 5: Shared Deployment Library and Guarded Update

**Files:**
- Create: `deploy/production/lib.sh`
- Create: `deploy/production/update.sh`
- Create: `tests/unit/release/test_production_scripts.py`

**Interfaces:**
- Produces: `acquire_deploy_lock`, `inspect_image`, `validate_image_pair`, `backup_postgres`, `wait_for_health`, `write_release_env`, `compose_recreate`, and `write_manifest` shell functions.
- Produces: `update.sh [--server-sha FULL_SHA --client-sha FULL_SHA]` with terminal results `NO_UPDATE_REQUIRED`, `UPDATE_SUCCESS`, `UPDATE_FAILED_ROLLBACK_READY`, or `ROLLBACK_FAILED`.
- Consumes: app-only Compose from Task 4 and exact GHCR labels from Task 2.

- [ ] **Step 1: Build a fake command harness and write no-op/locking RED tests**

```python
def test_update_same_digest_does_not_recreate(fake_runtime: FakeRuntime) -> None:
    fake_runtime.current_digest = fake_runtime.target_digest
    result = fake_runtime.run("update.sh")
    assert result.stdout.endswith("NO_UPDATE_REQUIRED\n")
    assert fake_runtime.calls("docker compose up") == []
    assert fake_runtime.calls("pg_dump") == []


def test_second_update_is_rejected_by_shared_lock(fake_runtime: FakeRuntime) -> None:
    fake_runtime.hold_lock()
    result = fake_runtime.run("update.sh")
    assert result.returncode != 0
    assert "deployment already in progress" in result.stderr
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_scripts.py -k 'same_digest or shared_lock' -q`

Expected: FAIL because scripts are absent.

- [ ] **Step 3: Implement lock, exact target resolution, label validation, and no-op exit**

```bash
exec 9>"$DEPLOY_ROOT/deploy.lock"
flock -n 9 || die "deployment already in progress"

if [ -n "$SERVER_SHA" ] || [ -n "$CLIENT_SHA" ]; then
  validate_full_sha "$SERVER_SHA"
  validate_full_sha "$CLIENT_SHA"
  target_tag="server-${SERVER_SHA:0:12}-client-${CLIENT_SHA:0:12}"
else
  target_tag=main
fi

docker pull "$IMAGE_REPOSITORY:$target_tag"
target_digest=$(resolve_repo_digest "$IMAGE_REPOSITORY:$target_tag")
validate_image_pair "$target_digest" "$SERVER_SHA" "$CLIENT_SHA"
test "$target_digest" != "$current_digest" || { echo NO_UPDATE_REQUIRED; exit 0; }
```

- [ ] **Step 4: Write backup-before-stop RED tests**

```python
def test_invalid_backup_never_stops_production(fake_runtime: FakeRuntime) -> None:
    fake_runtime.fail("pg_restore --list")
    result = fake_runtime.run("update.sh")
    assert result.returncode != 0
    assert fake_runtime.calls_matching("compose.*up|docker stop|docker rename") == []


def test_backup_and_manifests_are_mode_0600(fake_runtime: FakeRuntime) -> None:
    fake_runtime.run("update.sh")
    assert fake_runtime.mode("pre-update.dump") == 0o600
    assert fake_runtime.mode("release.env") == 0o600
    assert fake_runtime.mode("manifest.json") == 0o600
```

- [ ] **Step 5: Implement verified backup and atomic release selection**

```bash
umask 077
docker exec dclaw-postgres pg_dump -U qwenpaw -d qwenpaw --format=custom >"$dump_tmp"
docker run --rm --network none -v "$release_dir:/backup:ro" postgres:16-alpine \
  pg_restore --list "/backup/$(basename "$dump_tmp")" >"$list_tmp"
test -s "$list_tmp" || die "PostgreSQL backup verification failed"
mv "$dump_tmp" "$release_dir/pre-update.dump"

release_tmp=$(mktemp "$DEPLOY_ROOT/release.env.tmp.XXXXXX")
printf 'DCLAW_IMAGE=%s\nSERVER_SHA=%s\nCLIENT_SHA=%s\n' \
  "$target_digest" "$resolved_server_sha" "$resolved_client_sha" >"$release_tmp"
chmod 600 "$release_tmp"
mv "$release_tmp" "$DEPLOY_ROOT/release.env"
```

- [ ] **Step 6: Write health and automatic-rollback RED matrix**

```python
@pytest.mark.parametrize("failure", ["timeout", "container_exit", "oom", "local_api", "public_api", "label_drift"])
def test_update_failure_restores_previous_image(fake_runtime: FakeRuntime, failure: str) -> None:
    fake_runtime.inject_update_failure(failure)
    result = fake_runtime.run("update.sh")
    assert result.returncode != 0
    assert fake_runtime.running_image == fake_runtime.previous_digest
    assert "UPDATE_FAILED_ROLLBACK_READY" in result.stdout
    assert fake_runtime.database_restore_calls == 0


def test_health_window_is_at_least_420_seconds() -> None:
    assert read_health_timeout() >= 420
```

- [ ] **Step 7: Implement Compose recreate, health verification, and image-only rollback**

```bash
if ! compose_recreate "$target_digest" || ! wait_for_health 420; then
  save_failed_logs "$release_dir"
  write_release_env "$previous_digest" "$previous_server_sha" "$previous_client_sha"
  if compose_recreate "$previous_digest" && wait_for_health 420; then
    echo UPDATE_FAILED_ROLLBACK_READY
    exit 1
  fi
  echo ROLLBACK_FAILED >&2
  exit 2
fi
verify_public_api "https://dclaw.deepmega.cn/api/version"
verify_running_identity "$target_digest" "$resolved_server_sha" "$resolved_client_sha"
write_manifest "$release_dir"
echo UPDATE_SUCCESS
```

- [ ] **Step 8: Run Task 5 tests, syntax checks, and commit**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_scripts.py -q`

Run: `sh -n deploy/production/lib.sh deploy/production/update.sh`

Expected: PASS.

```bash
git add deploy/production/lib.sh deploy/production/update.sh tests/unit/release/test_production_scripts.py
git commit -m "feat: add guarded single-command DClaw updates"
```

---

### Task 6: Read-Only Status and Image-Only Rollback

**Files:**
- Create: `deploy/production/status.sh`
- Create: `deploy/production/rollback.sh`
- Modify: `tests/unit/release/test_production_scripts.py`

**Interfaces:**
- Consumes: helpers and manifest format from Task 5.
- Produces: `status.sh` with redacted local/remote identity and dependency health.
- Produces: `rollback.sh [--image immutable-digest]`, defaulting to `previous_image` from the latest successful manifest.

- [ ] **Step 1: Write status redaction RED tests**

```python
def test_status_is_read_only_and_redacts_secrets(fake_runtime: FakeRuntime) -> None:
    fake_runtime.production_env = "QWENPAW_DATABASE_URL=postgresql://user:secret@db/app\nGHCR_TOKEN=secret-token\n"
    result = fake_runtime.run("status.sh")
    assert result.returncode == 0
    assert "secret" not in result.stdout
    assert "postgresql://" not in result.stdout
    assert fake_runtime.mutating_calls == []
```

- [ ] **Step 2: Implement status from explicit safe fields**

```bash
docker inspect dclaw --format \
  'status={{.State.Status}} started={{.State.StartedAt}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} image_id={{.Image}}'
print_image_labels "$(running_image_id)"
check_named_container dclaw-postgres
check_named_container dclaw-redis
check_external_network dclaw-net
check_external_volume dclaw-data
check_external_volume dclaw-secrets
check_external_volume dclaw-backups
probe_api http://127.0.0.1:18088/api/version
probe_api https://dclaw.deepmega.cn/api/version
```

Do not inspect `.Config.Env`; obtain revision labels only from the image configuration.

- [ ] **Step 3: Write rollback RED tests**

```python
def test_rollback_only_switches_application_image(fake_runtime: FakeRuntime) -> None:
    result = fake_runtime.run("rollback.sh")
    assert result.stdout.endswith("ROLLBACK_SUCCESS\n")
    assert fake_runtime.running_image == fake_runtime.previous_digest
    assert fake_runtime.database_restore_calls == 0
    assert fake_runtime.removed_volumes == []
    assert fake_runtime.removed_networks == []
```

- [ ] **Step 4: Implement shared-lock rollback with the same 420-second gate**

```bash
acquire_deploy_lock
target_image=${explicit_image:-$(latest_manifest_field previous_image)}
validate_immutable_digest "$target_image"
previous_release=$(read_release_env)
write_release_env_from_image "$target_image"
if compose_recreate "$target_image" && wait_for_health 420; then
  echo ROLLBACK_SUCCESS
else
  write_release_env_from_record "$previous_release"
  die "rollback target failed health verification"
fi
```

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_scripts.py -q`

Run: `sh -n deploy/production/status.sh deploy/production/rollback.sh`

Expected: PASS.

```bash
git add deploy/production/status.sh deploy/production/rollback.sh tests/unit/release/test_production_scripts.py
git commit -m "feat: add safe DClaw status and rollback commands"
```

---

### Task 7: One-Time Adoption of the Existing Production Container

**Files:**
- Create: `deploy/production/adopt.sh`
- Modify: `tests/unit/release/test_production_scripts.py`

**Interfaces:**
- Consumes: current hand-created `dclaw`, app-only Compose, shared helpers, and current production image identity.
- Produces: a Compose-managed `dclaw` with identical image, port, restart policy, network, and named volumes; retains `dclaw-before-<timestamp>` as rollback container.

- [ ] **Step 1: Write adoption RED tests**

```python
def test_adoption_refuses_resource_drift(fake_runtime: FakeRuntime) -> None:
    fake_runtime.current_mounts.remove("dclaw-secrets:/app/working.secret")
    result = fake_runtime.run("adopt.sh")
    assert result.returncode != 0
    assert fake_runtime.calls("docker stop dclaw") == []


def test_failed_adoption_restores_original_container(fake_runtime: FakeRuntime) -> None:
    fake_runtime.fail_new_compose_health()
    result = fake_runtime.run("adopt.sh")
    assert result.returncode != 0
    assert fake_runtime.container("dclaw").image == fake_runtime.original_image
    assert fake_runtime.container("dclaw").running is True
```

- [ ] **Step 2: Run and preserve RED**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_scripts.py -k adoption -q`

Expected: FAIL because `adopt.sh` is absent.

- [ ] **Step 3: Implement exact preflight and preservation**

```bash
assert_container_name dclaw
assert_port_binding dclaw 127.0.0.1:18088:8088
assert_restart_policy dclaw unless-stopped
assert_network dclaw dclaw-net
assert_mount dclaw dclaw-data /app/working
assert_mount dclaw dclaw-secrets /app/working.secret
assert_mount dclaw dclaw-backups /app/working.backups
backup_postgres "$adoption_dir"
save_safe_container_facts "$adoption_dir"
docker tag "$current_image_id" "dclaw-local:pre-compose-$timestamp"
```

- [ ] **Step 4: Implement reversible rename/create sequence**

```bash
docker stop dclaw
docker rename dclaw "dclaw-before-$timestamp"
if compose_recreate "$current_image_id" && wait_for_health 420; then
  echo ADOPTION_SUCCESS
  exit 0
fi
docker rm -f dclaw 2>/dev/null || true
docker rename "dclaw-before-$timestamp" dclaw
docker start dclaw
wait_for_health 420 || die "adoption failed and original container could not be restored"
die "adoption failed; original production restored"
```

- [ ] **Step 5: Run full script suite and commit**

Run: `.venv/bin/python -m pytest tests/unit/release/test_production_scripts.py -q`

Run: `sh -n deploy/production/adopt.sh`

Expected: PASS.

```bash
git add deploy/production/adopt.sh tests/unit/release/test_production_scripts.py
git commit -m "feat: adopt existing DClaw container into compose"
```

---

### Task 8: Operator Runbook, End-to-End Verification, and Integration Handoff

**Files:**
- Create: `docs/operations/dclaw-container-release.md`
- Modify: `tests/unit/release/test_combined_workflow.py`
- Modify: `tests/unit/release/test_production_scripts.py`
- Verify only: all files created in Tasks 1–7 and the client worktree from Task 3.

**Interfaces:**
- Produces: exact installation and usage commands for `/opt/dclaw-deploy/{update,status,rollback}.sh`.
- Produces: documented GitHub secrets `DCLAW_CLIENT_READ_TOKEN` and `DCLAW_SERVER_DISPATCH_TOKEN`, plus server-only GHCR `read:packages` login.
- Produces: a two-repository handoff that can be pushed only after explicit user authorization.

- [ ] **Step 1: Write runbook contract RED tests**

```python
def test_runbook_documents_one_command_for_all_change_types() -> None:
    text = RUNBOOK.read_text()
    assert text.count("/opt/dclaw-deploy/update.sh") >= 3
    assert "server-only" in text
    assert "client-only" in text
    assert "server and client" in text


def test_runbook_never_recommends_destructive_cleanup_or_automatic_db_restore() -> None:
    text = RUNBOOK.read_text()
    assert "docker system prune" not in text
    assert "docker volume rm" not in text
    assert "ordinary rollback never restores PostgreSQL" in text
```

- [ ] **Step 2: Write the executable runbook**

Include these exact normal operations:

```bash
sudo /opt/dclaw-deploy/update.sh
sudo /opt/dclaw-deploy/status.sh
sudo /opt/dclaw-deploy/rollback.sh
```

Include this disconnect-safe update form:

```bash
nohup sudo /opt/dclaw-deploy/update.sh \
  >/opt/dclaw-deploy/logs/update-$(date +%Y%m%d-%H%M%S).log 2>&1 &
```

Document first adoption separately, `chmod 600` for env/release/manifest/backup files, `docker login ghcr.io --username 51taichi --password-stdin`, GitHub secret scopes, the 420-second startup expectation, immutable exact-SHA release syntax, log inspection, and the manual-only database restore boundary.

- [ ] **Step 3: Run focused server and client verification**

Run in server worktree:

```bash
.venv/bin/python -m pytest tests/unit/release -q
python -m compileall scripts/release tests/unit/release
sh -n deploy/production/*.sh
git diff --check
```

Run in client worktree:

```bash
npm --prefix console test -- dispatchContract.test.ts --run
npm --prefix console run lint
git diff --check
```

Expected: all PASS.

- [ ] **Step 4: Run repository regression appropriate to the changed surfaces**

Run in server worktree:

```bash
.venv/bin/python -m pytest tests/unit/release tests/integration/test_version.py -q
pre-commit run --files \
  .github/workflows/dclaw-combined-image.yml \
  scripts/release/resolve_release.py \
  scripts/release/assemble_context.sh \
  deploy/production/compose.production.yml \
  deploy/production/lib.sh \
  deploy/production/update.sh \
  deploy/production/status.sh \
  deploy/production/rollback.sh \
  deploy/production/adopt.sh \
  tests/unit/release/test_release_resolution.py \
  tests/unit/release/test_build_context.py \
  tests/unit/release/test_combined_workflow.py \
  tests/unit/release/test_production_compose.py \
  tests/unit/release/test_production_scripts.py \
  docs/operations/dclaw-container-release.md
```

If the existing Prettier bootstrap fails with the known npm `EALLOWGIT` environment error, record it verbatim and run every applicable Python/YAML/shell hook individually; do not report the aggregate hook as passing.

- [ ] **Step 5: Perform the plan self-review gates**

Run:

```bash
rg -n 'TBD|TODO|implement later|fill in details|docker system prune|docker volume rm' \
  .github/workflows/dclaw-combined-image.yml scripts/release deploy/production \
  tests/unit/release docs/operations/dclaw-container-release.md
rg -n 'Config.Env|DATABASE_URL=|Authorization:|GHCR_TOKEN=' deploy/production docs/operations/dclaw-container-release.md
```

Expected: no placeholders, destructive cleanup, unsafe environment dumps, or embedded credentials. Any intentional documentation mention must be a variable name without a value and covered by the redaction test.

- [ ] **Step 6: Commit runbook and final test refinements**

```bash
git add docs/operations/dclaw-container-release.md tests/unit/release
git commit -m "docs: document single-command DClaw releases"
```

- [ ] **Step 7: Request code review before integration**

Use `superpowers:requesting-code-review` twice: first for the server branch against server `origin/main`, then for the client branch against client `origin/main`. Resolve every Critical/Important finding with RED→GREEN evidence before continuing.

- [ ] **Step 8: Present exact integration state and ask for push authorization**

Report both branch names, full commit lists, fresh test outputs, workflow secret prerequisites, and the fact that production has not changed. Do not merge or push to `main` until the user explicitly authorizes it.

After authorization, push the client commit first, then the server commit so the client dispatch target exists when the server workflow is enabled. Confirm remote `main` SHAs and wait for the combined immutable image workflow to finish before installing or running production scripts.
