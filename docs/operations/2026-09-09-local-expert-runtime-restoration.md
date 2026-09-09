# Restore local expert UI and routes

The local `pricing-roundtrip-20260909` image inherited an older console and expert backend from `s6ff108447-c8db8c83dd`. Git main still contained the expert changes; the running container did not. The pricing-only deployment had checked pricing behavior without detecting the missing expert features.

Restored local runtime image: `dclaw-local:restored-experts-20260909`.

- Built console from committed client main `b93e113` in a separate directory; preserved uncommitted client layout work.
- Applied expert backend commits `b3dc5e1` and `c26edc1` to copies of the installed modules, preserving other runtime changes and the pricing fix.
- Updated `/Users/moxi/.dclaw-local/local.env` to select the restored image.
- Frontend: 6 expert page tests passed and production build succeeded.
- Backend: 37 expert/admin/ordering tests passed.
- Deployment: container healthy; served HTML and expert JS `index-C_6QnxGN.js` match build byte-for-byte; both `/api/admin/sealed-agents/{agent_id}/avatar` and `/banner` advertise POST.

For future local updates, verify both front-end assets and backend feature routes. Do not assume an existing base image contains everything on main. Uncommitted workspace changes are not evidence of deployed functionality.
