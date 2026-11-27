class LuyuAigcFixtureRuntime:
    async def handle(self, request, host):
        binding = {
            "installation_id": request.installation_id,
            "conversation_id": request.session_id,
            "agent_task_id": "task-fixture",
            "content_revision": 1,
            "material_task_id": "material-fixture",
            "canvas_id": "canvas-fixture",
            "node_id": "video-fixture",
        }
        await host.call("card.create", {
            "binding": binding,
            "event_id": f"{request.invocation_id}:card",
            "idempotency_key": f"{request.invocation_id}:card",
            "payload": {"card_type": "aigc_material_task", "title": "制作视频素材"},
        })
        created = await host.call("aigc.task.create", {
            "binding": binding,
            "event_id": f"{request.invocation_id}:task",
            "idempotency_key": f"{request.invocation_id}:task",
            "payload": {"operation_id": "aigc.text_to_video.create"},
        })
        await host.call("runtime.complete", {
            "invocation_id": request.invocation_id,
            "message": {"reply": f"AIGC任务已建立：{created['task']['status']}"},
        })


def create_runtime():
    return LuyuAigcFixtureRuntime()
