"""Register the Jev private-message routing tool."""

from .routing import route_private_message_jev


class JevPrivateRoutingPlugin:
    def register(self, api):
        api.register_tool(
            tool_name="route_private_message_jev",
            tool_func=route_private_message_jev,
            description="Attribute a Douyin private message to a candidate comment task with Jev",
        )


plugin = JevPrivateRoutingPlugin()
