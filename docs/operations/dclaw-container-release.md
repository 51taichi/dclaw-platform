# DClaw combined-image releases

This runbook publishes `dclaw-server` and `dclaw-client` as one image and
updates the existing production application in place. It does not create a
second production DClaw. The public endpoint remains
`https://dclaw.deepmega.cn`, and Nginx continues to proxy the application on
`127.0.0.1:18088`.

## Fixed production boundary

The production Compose project owns only the application container `dclaw`.
It references, but never manages, the existing resources:

- containers `dclaw-postgres` and `dclaw-redis`;
- network `dclaw-net`;
- volumes `dclaw-data`, `dclaw-secrets`, and `dclaw-backups`;
- host binding `127.0.0.1:18088:8088`.

The release scripts do not remove old images, rollback containers, database
dumps, networks, or volumes. Cleanup is a separate, reviewed maintenance
operation.

## GitHub configuration

The `dclaw-server` repository needs:

- Actions permission to read repository contents and write packages;
- `DCLAW_CLIENT_READ_TOKEN`, scoped to read only the private
  `51taichi/dclaw-client` repository.

The `dclaw-client` repository needs:

- `DCLAW_SERVER_DISPATCH_TOKEN`, scoped only to send a repository dispatch to
  `51taichi/dclaw-server`.

A server `main` push builds the event server SHA with the client `main` SHA. A
client `main` push dispatches its immutable client SHA and builds it with the
then-current server `main` SHA. Manual workflow dispatch accepts a complete
40-character SHA pair. The resulting image is published to
`ghcr.io/51taichi/dclaw` as both `server-<12>-client-<12>` and, after label
verification, `main`.

## Install the production tooling

Run these commands from an approved checkout of `dclaw-server` on the Alibaba
Cloud host:

```bash
sudo install -d -m 700 /opt/dclaw-deploy /opt/dclaw-deploy/logs
sudo install -m 644 deploy/production/compose.production.yml \
  /opt/dclaw-deploy/compose.production.yml
sudo install -m 755 \
  deploy/production/lib.sh \
  deploy/production/build-release.sh \
  deploy/production/deploy-release.sh \
  deploy/production/deploy-result.sh \
  deploy/production/update.sh \
  deploy/production/status.sh \
  deploy/production/rollback.sh \
  deploy/production/adopt.sh \
  /opt/dclaw-deploy/
```

When a server-only release must keep the current production client, build the
exact pair instead of following either repository's moving `main` branch:

```bash
sudo /opt/dclaw-deploy/build-release.sh \
  --server-sha 0123456789abcdef0123456789abcdef01234567 \
  --client-sha 89abcdef0123456789abcdef0123456789abcdef
```

Both arguments are required together and must be complete 40-character
commits. The script downloads those immutable snapshots, labels the image with
the same full commits, and writes them to the pending release receipt. Calling
the script without either argument retains the existing behavior of resolving
both `main` branches once at build start.

Do not copy `production.env.example` over the current environment. The first
adoption captures the existing container environment directly into protected
`/opt/dclaw-deploy/production.env` without printing it.

If the GHCR package is private, create a token with only `read:packages`, then
log in without placing it in the command line:

```bash
read -r -s -p 'GHCR read token: ' GHCR_READ_TOKEN
printf '\n'
printf '%s' "$GHCR_READ_TOKEN" |
  docker login ghcr.io --username 51taichi --password-stdin
unset GHCR_READ_TOKEN
```

## One-time adoption

Use this once while the existing `dclaw` is still the hand-created production
container:

```bash
sudo /opt/dclaw-deploy/adopt.sh
```

Before stopping anything, `adopt.sh` verifies the exact port, restart policy,
network, three volumes, PostgreSQL, Redis, image labels, and a fresh validated
PostgreSQL custom-format dump. It preserves the old container as
`dclaw-before-<timestamp>`. If the Compose-managed replacement does not pass
the 420 seconds health gate, the script restores and starts the original
container.

Confirm the result:

```bash
sudo /opt/dclaw-deploy/status.sh
docker inspect dclaw --format \
  '{{.Name}} {{.Image}} {{range .Mounts}}{{.Name}}:{{.Destination}} {{end}}'
```

## Normal updates

The command is identical for a server-only change, a client-only change, or a
change to both server and client:

```bash
sudo /opt/dclaw-deploy/update.sh
```

The command pulls `ghcr.io/51taichi/dclaw:main`, validates both full revision
labels, exits with `NO_UPDATE_REQUIRED` without a backup or recreate when the
image ID is unchanged, and otherwise performs the protected update.

For an exact previously built pair:

```bash
sudo /opt/dclaw-deploy/update.sh \
  --server-sha 0123456789abcdef0123456789abcdef01234567 \
  --client-sha 89abcdef0123456789abcdef0123456789abcdef
```

Both values must be complete SHAs. The script derives the immutable pair tag
and rejects the image unless both labels match exactly.

Alibaba Cloud Workbench or SSH disconnects must not own the update process.
Start it in the background and inspect its log:

```bash
LOG=/opt/dclaw-deploy/logs/update-$(date +%Y%m%d-%H%M%S).log
nohup sudo /opt/dclaw-deploy/update.sh >"$LOG" 2>&1 &
printf 'pid=%s log=%s\n' "$!" "$LOG"
tail -f "$LOG"
```

The shared deployment lock rejects a second update or rollback while one is
running. A normal start can take approximately 282 seconds on the current
host, so the automated health window is 420 seconds. A temporary connection
reset during this interval does not by itself mean the update failed.

## Status

```bash
sudo /opt/dclaw-deploy/status.sh
```

The command reads only safe fields: container state, image ID/digest,
server/client labels, dependency names, local/public API health, and the last
release manifest. It never prints `.Config.Env`, the database URL, GHCR token,
authorization headers, or secret-volume contents.

## Application rollback

To return to the image saved before the last successful release:

```bash
sudo /opt/dclaw-deploy/rollback.sh
```

To select a retained immutable image explicitly:

```bash
sudo /opt/dclaw-deploy/rollback.sh \
  --image ghcr.io/51taichi/dclaw@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

An ordinary rollback never restores PostgreSQL. It changes only the
application image, uses the same lock and 420 seconds health gate, and keeps
the existing database, Redis, network, and volumes attached.

An image rollback does not undo integration-delivery data changes. To restore
one Agent and its isolated knowledge from a specific delivery operation, use
the authenticated operation restore endpoint documented in
`docs/integration-delivery-write-api.zh-CN.md` before or after the image
rollback, as appropriate. Do not restore the whole database for a single
delivery operation.

## Integration-delivery signing material

The optional write adapter is disabled operationally unless its client secret
and signing material are configured. Store the Ed25519 private signer at:

```text
${QWENPAW_SECRET_DIR}/integration_delivery_signer.json
```

The file must be owned by the application runtime user and mode `0600`. Its
public key must be present in
`sealed_agents/trusted_signers.json`; a signer used for super experts must also
be present in `sealed_agents/official_super_expert_signers.json`. Never print,
copy into an image layer, or place the private key in `production.env`.

Provision and verify the identity inside the runtime image. Both commands emit
status only and never key material:

```bash
python -m qwenpaw.app.integration_delivery.signer_provisioning --provision
python -m qwenpaw.app.integration_delivery.signer_provisioning --check
```

Provisioning is idempotent and refuses to overwrite a conflicting signer ID.
Restart DClaw after the first provision so the sealed-Agent service reloads
both trust registries.

Before an update, retain the running image digest and confirm that the
`dclaw-data` and `dclaw-secrets` volumes are attached. Delivery operation
receipts live under `integration_delivery/operations/` in the data volume and
must survive container replacement. After an update, validate the existing
read endpoints first, then validate the four internal write-adapter endpoints
with a non-production Agent before allowing an upstream publisher to use them.

## Backups and disaster recovery

Each non-no-op update and the initial adoption creates a custom-format
PostgreSQL dump and validates it with `pg_restore --list` before the application
is stopped or recreated. Release manifests, facts, dumps, `production.env`,
and `release.env` must remain owned by root and mode `0600` (release directories
are mode `0700`).

Database restore is a separate disaster-recovery decision. Use it only after
stopping writes, confirming that an image-only rollback cannot run against the
forward-compatible schema, selecting the matching pre-update dump, and taking
a second current backup. Restoring a dump automatically could discard valid
writes made after cutover, so none of the normal update or rollback commands
perform that operation.

## Acceptance after an update

Verify all of the following before declaring the release complete:

1. `status.sh` reports the intended full server/client labels and no OOM or
   restart loop.
2. Local `/api/version` and `https://dclaw.deepmega.cn/api/version` respond.
3. Existing accounts, historical chats, AIGC projects, and workspaces are
   present.
4. The admin console, wallet, Agent experience library, and Sealed Agent pages
   pass smoke testing.
5. `docker inspect dclaw` still shows `dclaw-net` and the three named volumes.
6. The preceding immutable image and the pre-update PostgreSQL dump remain
   readable.
