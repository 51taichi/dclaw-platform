# agent.execute v2

Use `agent_execute_api_demo.py`; do not infer the contract version from the
request body.

- Agent Loop: `messages` with omitted `execution_mode`, or explicit
  `execution_mode=agent_loop`.
- Model-only text candidate: `execution_mode=candidate` plus `messages`.
- Model-only JSON candidate: explicit `candidate` plus
  `response_format=json_object`.
- `response_format` is invalid in Agent Loop mode.

The Host selects this contract from the signed Release capability declaration.
Existing v1 Releases keep their original candidate default.
