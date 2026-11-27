# Minimal local example

Run the example from the developer pack root:

```text
python dclaw_developer.py demo --workspace ./demo-work
```

The command materializes the versioned project template as
`example-local-agent`, declares required local preflight, installs verified
behavior evidence, runs the Windows local capability in simulator mode, runs
the Agent tests, creates an ephemeral Ed25519 test signer, builds the sealed
Agent ZIP, and verifies it. The generated workspace is the complete example;
this definition file avoids maintaining a second drifting copy of the project
template.
