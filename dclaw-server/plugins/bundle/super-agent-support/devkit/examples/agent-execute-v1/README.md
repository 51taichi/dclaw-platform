# agent.execute / runtime.fail v1

Use `agent_execute_api_demo.py`; do not invent argument combinations.

- Text candidate: `messages` only.
- JSON candidate: `messages` plus `response_format=json_object`.
- Tool loop: `execution_mode=agent_loop`, `messages`, and a non-empty trusted `instruction`.
- `instruction` is invalid in candidate mode. `response_format` is invalid in `agent_loop`.
- A failed runtime must call `runtime.fail` once with the current invocation ID and either a legacy code or an uppercase dotted stable code such as `HOST.AGENT_EXECUTE_FAILED`.

The Host owns card persistence. A card must be validated against the live catalog,
created through `interaction.card.create/1`, and verified with the created receipt.
If the same invocation fails before completion, the platform cancels only a card
that invocation actually created and that remains PENDING. Replays, submitted cards,
and cards created by another invocation are never cancelled by this compensation.
