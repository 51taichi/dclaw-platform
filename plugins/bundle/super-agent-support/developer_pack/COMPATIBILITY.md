# Compatibility Matrix

| Component | Supported version |
|---|---|
| Developer pack | 1.0.x through 1.10.x |
| Development standard | 2.1 through 2.35 |
| Super Agent DevKit | 1.2.x through 1.9.x |
| Super Expert manifest | 3 |
| Runtime / runtime host | 1 |
| Local execution contract | 1.0, 1.1 and 1.2 |
| Super Agent support contract | 1 |
| Business service installation identity | 1 |
| DClaw server | >= 1.1.10 |
| Support plugin for local execution contracts | >= 1.4.0 |
| Support plugin for developer pack 1.0.x download | >= 1.5.0 |
| Support plugin for developer pack 1.1.x download | >= 1.6.0 |
| Support plugin for developer pack 1.2.x download | >= 1.7.0 |
| Support plugin for developer pack 1.3.x download | >= 1.8.0 |
| Support plugin for developer pack 1.4.0 download | >= 1.9.0 |
| Support plugin for developer pack >= 1.4.1 download | >= 1.9.1 |
| Support plugin for developer pack >= 1.5.0 download | >= 1.10.0 |
| Support plugin for developer pack >= 1.5.1 download | >= 1.10.1 |
| Support plugin for developer pack >= 1.5.2 download | >= 1.10.2 |
| Support plugin for developer pack >= 1.5.3 download | >= 1.11.2 |
| Support plugin for developer pack >= 1.5.4 download | >= 1.11.3 |
| Support plugin for developer pack >= 1.6.0 download | >= 1.12.0 |
| Support plugin for developer pack >= 1.7.0 download | >= 1.13.0 |
| Support plugin for developer pack >= 1.8.0 download | >= 1.14.0 |
| Support plugin for developer pack >= 1.9.0 download | >= 1.15.0 |
| Support plugin for developer pack >= 1.9.1 download | >= 1.15.1 |
| Support plugin for developer pack >= 1.9.3 download | >= 1.16.0 |
| Support plugin for self-service package type and developer pack >= 1.10.0 | >= 1.17.0 |
| Support plugin for `runtime.failure.read/1` | >= 1.18.12 |
| Support plugin for startup failure diagnostics and durable failed turns | >= 1.18.13 |
| Support plugin for preserving prior memory on failed turns | >= 1.18.14 |
| Support plugin for signed workspace state continuity | >= 1.18.15 |
| Support plugin for activation state preflight and internal history isolation | >= 1.18.16 |
| Support plugin for interaction receipts and safe failure stages | >= 1.18.19 |
| DClaw Windows client for required preflight | >= 2.6.12 |
| DClaw Windows client for local file workflows | >= 2.6.13 |
| Runner | >= 1.0.0; >= 1.1.0 for device protocol 2 file workflows; >= 1.2.0 for public Components; >= 1.3.0 for explicit non-entry Component export bindings |

The pack keeps the DevKit 1.2/1.3/1.4 sealing format unchanged. Existing Agent
packages built under standard 1.x or 2.0 remain accepted by their declared
platform contracts. The new project evidence and resource gates apply when
rebuilding with this pack; they do not rewrite, invalidate, or silently upgrade
an existing signed package.

Breaking protocol changes require a new protocol major and a parallel
compatibility path. The current and previous protocol major must coexist during
the published deprecation window.
