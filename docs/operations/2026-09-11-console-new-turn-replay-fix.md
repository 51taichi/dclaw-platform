# Console new-turn replay fix

Observed in chat 208476b3-f0aa-4f8b-9803-e8644fe0fd7c: only the initial greeting reached the Agent; a follow-up submission displayed the same opening while the previous task was still active. Console used attach_or_start for both new submissions and existing streams, causing a new payload to be discarded in favor of replaying the previous buffer.

Console new submissions now use start_new, waiting outside the tracker lock for the preceding run before atomically starting a fresh run. Explicit reconnect continues to use attach. Other callers of attach_or_start retain their behavior. Waiting request cancellation releases its concurrency permit without cancelling the previous run. No LuYu prompt change or history rewrite.

Validation: reproduction test retains old stream while starting a new turn, checks explicit reconnect replay, and confirms new submission receives only its own answer. 95 console, task-limit, reload, team, Open API, mobile and performance tests passed. Deployment replaces only task_tracker.py and routers/console.py; prior image and environment are retained for rollback. No paid model generation performed for verification.
