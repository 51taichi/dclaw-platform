# Jev private-message routing

Install with `qwenpaw plugin install plugins/tool/jev-private-routing`, then restart DClaw. Set `TYPESAFE_API_KEY` in the DClaw server process environment. The key is read at call time and is never passed to the Agent prompt or stored in its workspace.

Only `douyin_engagement_agent` enables `route_private_message_jev` in its `agent.json`. Plugin registration adds a disabled entry to other Agent profiles. The tool accepts the latest private message, same-conversation history, and Bot Server candidate tasks containing only `taskId`, `name`, and `routingDescription`.

The tool calls TypeSafe `POST /v1/systemone` with `jev-latest` and a Choice with `no_match`. It batches more than 200 tasks and supports at most 400; multiple matching batches, weak probabilities, missing credentials, and API failures cannot produce a task selection. Thresholds are defined in `routing.py` and should be calibrated against labeled Douyin messages before broad rollout.
