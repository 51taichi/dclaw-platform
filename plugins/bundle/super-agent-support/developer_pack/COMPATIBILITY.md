# Compatibility Matrix

| Component | Supported version |
|---|---|
| Developer pack | 1.0.x and 1.1.x |
| Development standard | 2.1 and 2.2 |
| Super Agent DevKit | 1.2.x |
| Super Expert manifest | 3 |
| Runtime / runtime host | 1 |
| Local execution contract | 1.0 |
| Super Agent support contract | 1 |
| DClaw server | >= 1.1.10 |
| Support plugin for local execution contracts | >= 1.4.0 |
| Support plugin for developer pack 1.0.x download | >= 1.5.0 |
| Support plugin for developer pack 1.1.x download | >= 1.6.0 |
| DClaw Windows client for required preflight | >= 2.6.12 |
| Runner | >= 1.0.0, subject to capability descriptor |

The pack keeps the DevKit 1.2 sealing format unchanged. Existing Agent packages
built under standard 1.x or 2.0 remain accepted by their declared platform
contracts. The new project evidence gate applies when rebuilding with this pack;
it does not rewrite, invalidate, or silently upgrade an existing signed package.

Breaking protocol changes require a new protocol major and a parallel
compatibility path. The current and previous protocol major must coexist during
the published deprecation window.
