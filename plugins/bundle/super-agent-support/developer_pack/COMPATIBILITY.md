# Compatibility Matrix

| Component | Supported version |
|---|---|
| Developer pack | 1.0.x, 1.1.x, 1.2.x and 1.3.x |
| Development standard | 2.1, 2.2, 2.3, 2.4 and 2.5 |
| Super Agent DevKit | 1.2.x and 1.3.x |
| Super Expert manifest | 3 |
| Runtime / runtime host | 1 |
| Local execution contract | 1.0 and 1.1 |
| Super Agent support contract | 1 |
| DClaw server | >= 1.1.10 |
| Support plugin for local execution contracts | >= 1.4.0 |
| Support plugin for developer pack 1.0.x download | >= 1.5.0 |
| Support plugin for developer pack 1.1.x download | >= 1.6.0 |
| Support plugin for developer pack 1.2.x download | >= 1.7.0 |
| Support plugin for developer pack 1.3.x download | >= 1.8.0 |
| Support plugin for developer pack 1.4.x download | >= 1.9.0 |
| DClaw Windows client for required preflight | >= 2.6.12 |
| DClaw Windows client for local file workflows | >= 2.6.13 |
| Runner | >= 1.0.0; >= 1.1.0 for device protocol 2 file workflows |

The pack keeps the DevKit 1.2/1.3 sealing format unchanged. Existing Agent packages
built under standard 1.x or 2.0 remain accepted by their declared platform
contracts. The new project evidence gate applies when rebuilding with this pack;
it does not rewrite, invalidate, or silently upgrade an existing signed package.

Breaking protocol changes require a new protocol major and a parallel
compatibility path. The current and previous protocol major must coexist during
the published deprecation window.
