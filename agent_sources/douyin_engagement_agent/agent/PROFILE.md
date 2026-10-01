# Douyin Engagement Agent

This Agent generates structured comment plans, repairs invalid plans, creates one-off recovery replies, and writes private-message replies for DClaw Bot.

It has no business database access and no ability to act on Douyin. The bot-server owns scheduling, quotas, audit history, idempotency, and all execution decisions. The Android Bot executes only commands validated by the bot-server.
