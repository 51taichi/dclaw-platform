# Manual top-up wallet release

This release is built from two immutable Git revisions:

- `dclaw-server`: the API, schema, accounting workflow, and Dockerfile.
- `dclaw-client`: the console source copied into `console/` in the temporary
  Docker build context.

Never build the production image from an uncommitted checkout. Record both
commit SHAs and the resulting image digest in the deployment log.

## 1. Prepare and verify source revisions

```sh
SERVER_REPO=/srv/releases/dclaw-server
CLIENT_REPO=/srv/releases/dclaw-client
SERVER_SHA='<reviewed dclaw-server commit>'
CLIENT_SHA='<reviewed dclaw-client commit>'

git -C "$SERVER_REPO" fetch --prune origin
git -C "$CLIENT_REPO" fetch --prune origin
git -C "$SERVER_REPO" cat-file -e "${SERVER_SHA}^{commit}"
git -C "$CLIENT_REPO" cat-file -e "${CLIENT_SHA}^{commit}"
git -C "$SERVER_REPO" status --porcelain
git -C "$CLIENT_REPO" status --porcelain
```

Both status commands must be empty. Before production, run the server billing
tests and the client test/build commands recorded in the release report.

## 2. Back up the running installation

Follow the database, named-volume, configuration, secret, image-digest, and
Nginx backup procedure in `docs/operations/open-api-billing-rollout.md`.
Do not proceed unless the PostgreSQL dump verifies successfully and the old
image digest is locally available or pullable.

In addition, record the current container configuration:

```sh
docker inspect dclaw > /srv/backups/dclaw-before-wallet-inspect.json
docker image inspect "$(docker inspect -f '{{.Image}}' dclaw)" \
  > /srv/backups/dclaw-before-wallet-image.json
```

## 3. Assemble the reviewed build context

The server repository intentionally does not track a duplicate console tree.
Its Dockerfile builds `console/`, so inject the reviewed client console only in
an isolated temporary context.

```sh
BUILD_ROOT=$(mktemp -d /srv/releases/dclaw-wallet-build.XXXXXX)
trap 'rm -rf "$BUILD_ROOT"' EXIT INT TERM

git -C "$SERVER_REPO" archive "$SERVER_SHA" | tar -x -C "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/console"
git -C "$CLIENT_REPO" archive "$CLIENT_SHA" console \
  | tar -x --strip-components=1 -C "$BUILD_ROOT/console"

test -f "$BUILD_ROOT/deploy/Dockerfile"
test -f "$BUILD_ROOT/console/package-lock.json"
test -f "$BUILD_ROOT/console/src/pages/Wallet/index.tsx"
test -f "$BUILD_ROOT/console/src/pages/AdminBilling/index.tsx"
```

Build and label the candidate image:

```sh
SERVER_SHORT=$(printf '%s' "$SERVER_SHA" | cut -c1-12)
CLIENT_SHORT=$(printf '%s' "$CLIENT_SHA" | cut -c1-12)
IMAGE="dclaw-local:wallet-${SERVER_SHORT}-client-${CLIENT_SHORT}"
docker build \
  --file "$BUILD_ROOT/deploy/Dockerfile" \
  --label "cn.deepmega.dclaw.server-revision=$SERVER_SHA" \
  --label "cn.deepmega.dclaw.client-revision=$CLIENT_SHA" \
  --tag "$IMAGE" \
  "$BUILD_ROOT"
docker image inspect "$IMAGE" --format '{{json .RepoDigests}} {{json .Config.Labels}}'
```

## 4. Candidate checks and production switch

Use an isolated candidate database, Redis volume, working volume, secret
directory, Compose project, and host port. Do not attach the candidate to the
production database or production volumes. Verify at minimum:

- login and existing chat/AIGC workflows;
- `/wallet` balance, products, QR configuration, claims, ledger, and usage;
- `/admin/billing` claim review, products, pricing, usage, reconciliation, and
  rollout tabs;
- one test claim can be submitted and approved exactly once;
- replaying the approval does not add a second ledger entry;
- another user cannot see the claim or its ledger entry.

After approval, deploy the same image digest with the existing production
Compose configuration. The application lifespan performs the idempotent schema
bootstrap before serving requests. Keep billing in the persisted safe rollout
mode required by `open-api-billing-rollout.md`; changing the image does not by
itself authorize `enforced` mode.

Switch the reverse proxy only after the new container is healthy. Record the
server SHA, client SHA, image ID/digest, database dump, and switch timestamp.

## 5. Rollback

For an application-only problem, point the existing production configuration
back to the recorded old image digest and restart the container. Do not restore
the database merely to roll back application code: the new billing schema is
forward-compatible and the old application ignores the additional tables.

Restore PostgreSQL only for proven database corruption or an explicitly
approved destructive-data rollback. A database restore discards legitimate
wallet, claim, audit, and usage activity created after the dump, so it requires
a maintenance window and business approval.
