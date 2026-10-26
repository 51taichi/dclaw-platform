"""Compatibility import; implementation is owned by super-agent-support."""

from qwenpaw.bundled_plugins import reexport_bundled_plugin_module

reexport_bundled_plugin_module(
    globals(),
    plugin_id="dclaw.super-agent-support",
    directory_name="super-agent-support",
    submodule="session",
)
