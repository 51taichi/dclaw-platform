# Background chat titles

Console schedules title generation as a separate async task after the response stream finishes. Title completion no longer gates the foreground conversation run. The task owns a separate billing execution with a `:title` key, is retained while running, and is deduplicated per Agent/chat. Existing compare-and-set title writes preserve manual renames. Model and Skill behavior, LuYu 1.0.9, and response streaming remain unchanged.

Validation: 41 background-title, title-generator, console, and new-turn tests passed. Checked the authenticated all-chats endpoint before deployment: zero running conversations. Only routers/console.py is replaced; previous image and local.env retained for rollback. No paid model call used for deployment verification.
