# -*- coding: utf-8 -*-
# pylint:disable=too-many-nested-blocks
"""Central plugin registry."""

from typing import Any, Callable, Dict, List, Mapping, Optional, Type
from dataclasses import dataclass, field
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

# Registered on the console SPA catch-all in ``_app.py`` so plugin HTTP
# routes can be inserted *before* it (routes appended later would lose).
_CONSOLE_SPA_CATCHALL_ROUTE_NAME = "qwenpaw_console_spa_catchall"


def _find_console_spa_route_index(app: Any) -> Optional[int]:
    """Return the index of the SPA ``/{full_path:path}`` route if present."""
    routes = getattr(app.router, "routes", None)
    if routes is None:
        return None
    for i, route in enumerate(routes):
        if getattr(route, "name", None) == _CONSOLE_SPA_CATCHALL_ROUTE_NAME:
            return i
    return None


def _mount_plugin_http_on_app(
    app: Any,
    router: APIRouter,
    *,
    full_path_prefix: str,
    tags: Optional[List[Any]],
) -> List[Any]:
    """Include *router* on *app* so it matches before the console SPA route."""
    routes = app.router.routes
    spa_idx = _find_console_spa_route_index(app)
    n_before = len(routes)
    app.include_router(router, prefix=full_path_prefix, tags=tags)
    added = routes[n_before:]
    del routes[n_before:]
    if spa_idx is not None:
        for route in reversed(added):
            routes.insert(spa_idx, route)
    else:
        routes.extend(added)
    # Invalidate the cached OpenAPI schema so the next /openapi.json
    # request reflects the newly added plugin routes. FastAPI caches
    # the schema on first access and never regenerates it otherwise.
    app.openapi_schema = None
    return list(added)


@dataclass
class ProviderRegistration:
    """Provider registration record."""

    plugin_id: str
    provider_id: str
    provider_class: Type
    label: str
    base_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookRegistration:
    """Hook registration record."""

    plugin_id: str
    hook_name: str
    callback: Callable
    priority: int = 100


@dataclass
class ControlCommandRegistration:
    """Control command registration record."""

    plugin_id: str
    handler: Any  # BaseControlCommandHandler
    priority_level: int = 10


@dataclass
class HttpRouterRegistration:
    """HTTP routes contributed by a backend plugin under ``/api``."""

    plugin_id: str
    prefix: str
    routes: List[Any]


@dataclass
class AsgiAppRegistration:
    """ASGI application mounted by a plugin under ``/api``."""

    plugin_id: str
    prefix: str
    route: Any


@dataclass(frozen=True)
class PublicHttpRouteRegistration:
    """Exact anonymous HTTP route declared by one backend plugin."""

    plugin_id: str
    method: str
    path: str


@dataclass(frozen=True)
class PlatformCapabilityRegistration:
    """Versioned platform capability contributed by a plugin."""

    plugin_id: str
    capability_id: str
    contract_version: str
    group: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkspaceContextEnricherRegistration:
    """Trusted workspace-context callback contributed by a plugin."""

    plugin_id: str
    name: str
    callback: Callable
    priority: int = 100


@dataclass(frozen=True)
class WorkspaceTurnHandlerRegistration:
    """Plugin-owned handler for one orchestration capability."""

    plugin_id: str
    capability_id: str
    callback: Callable


@dataclass(frozen=True)
class AigcEventConsumerFactoryRegistration:
    """Factory contributing an optional consumer to core AIGC recovery."""

    plugin_id: str
    name: str
    factory: Callable


@dataclass(frozen=True)
class AigcCanvasPolicyRegistration:
    """Plugin policy evaluated for a managed AIGC canvas."""

    plugin_id: str
    name: str
    callback: Callable


@dataclass(frozen=True)
class SealedPackageTypeRegistration:
    """Lifecycle handler for an extension-owned sealed package type."""

    plugin_id: str
    package_type: str
    handler: Any


class PluginRegistry:  # pylint:disable=too-many-public-methods
    """Central plugin registry (Singleton).

    This registry manages all plugin registrations and provides
    a centralized way to access plugin capabilities.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        # Initialize _initialized first to avoid pylint error
        if not hasattr(self, "_initialized"):
            self._initialized = False

        if self._initialized:
            return

        self._providers: Dict[str, ProviderRegistration] = {}
        self._startup_hooks: List[HookRegistration] = []
        self._shutdown_hooks: List[HookRegistration] = []
        self._control_commands: List[ControlCommandRegistration] = []
        self._runtime_helpers = None
        self._plugin_manifests: Dict[str, Dict[str, Any]] = {}
        self._plugin_http_app: Optional[Any] = None
        self._http_router_registrations: List[HttpRouterRegistration] = []
        self._asgi_app_registrations: List[AsgiAppRegistration] = []
        self._public_http_routes: Dict[
            tuple[str, str], PublicHttpRouteRegistration
        ] = {}
        self._http_prefix_to_plugin: Dict[str, str] = {}
        self._platform_capabilities: Dict[
            str,
            PlatformCapabilityRegistration,
        ] = {}
        self._workspace_context_enrichers: List[
            WorkspaceContextEnricherRegistration
        ] = []
        self._workspace_turn_handlers: Dict[
            str,
            WorkspaceTurnHandlerRegistration,
        ] = {}
        self._aigc_event_consumer_factories: List[
            AigcEventConsumerFactoryRegistration
        ] = []
        self._aigc_canvas_policies: List[AigcCanvasPolicyRegistration] = []
        self._sealed_package_types: Dict[
            str,
            SealedPackageTypeRegistration,
        ] = {}

        self._initialized = True

    def set_plugin_http_app(self, app: Any) -> None:
        """Attach the FastAPI application used to mount plugin HTTP routes.

        Must be called once before any ``register_http_router`` (typically
        from application lifespan before ``load_all_plugins``).

        Args:
            app: The root ``FastAPI`` instance.
        """
        self._plugin_http_app = app

    def register_http_router(
        self,
        plugin_id: str,
        router: APIRouter,
        *,
        prefix: str,
        tags: Optional[List[Any]] = None,
    ) -> None:
        """Mount a plugin ``APIRouter`` at ``/api`` + *prefix*.

        Args:
            plugin_id: Owning plugin id
            router: Router defining plugin HTTP handlers
            prefix: URL prefix under ``/api``, e.g. ``/pets`` for
                ``GET /api/pets/...``. Must start with ``/`` and must not
                end with ``/`` (except the single slash ``/`` is not allowed).
            tags: Optional OpenAPI tags for included routes

        Raises:
            RuntimeError: If the FastAPI app was not configured.
            ValueError: On invalid *prefix* or duplicate prefix.
        """
        http_app = self._plugin_http_app
        if http_app is None:
            raise RuntimeError(
                "Cannot register plugin HTTP routes: FastAPI app was not "
                "configured (internal setup error).",
            )

        normalized = prefix.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        normalized = normalized.rstrip("/") or "/"
        if normalized == "/":
            raise ValueError(
                "Plugin HTTP prefix must not be '/' alone; use a path "
                "segment such as '/pets'.",
            )

        if normalized in self._http_prefix_to_plugin:
            owner = self._http_prefix_to_plugin[normalized]
            raise ValueError(
                f"Plugin HTTP prefix '{normalized}' is already registered "
                f"by plugin '{owner}'",
            )

        effective_tags: Optional[List[Any]]
        if tags is not None:
            effective_tags = list(tags)
        else:
            effective_tags = [f"plugin:{plugin_id}"]

        full_prefix = f"/api{normalized}"
        added = _mount_plugin_http_on_app(
            http_app,
            router,
            full_path_prefix=full_prefix,
            tags=effective_tags,
        )

        self._http_router_registrations.append(
            HttpRouterRegistration(
                plugin_id=plugin_id,
                prefix=normalized,
                routes=added,
            ),
        )
        self._http_prefix_to_plugin[normalized] = plugin_id
        logger.info(
            "Registered HTTP routes for plugin '%s' at prefix '/api%s'",
            plugin_id,
            normalized,
        )

    def get_http_router_registrations(self) -> List[HttpRouterRegistration]:
        """Return a copy of HTTP router registrations (for diagnostics)."""
        return list(self._http_router_registrations)

    @staticmethod
    def _normalize_http_prefix(prefix: str) -> str:
        normalized = prefix.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        normalized = normalized.rstrip("/") or "/"
        if normalized == "/":
            raise ValueError(
                "Plugin HTTP prefix must not be '/' alone; use a path "
                "segment such as '/pets'.",
            )
        return normalized

    def register_asgi_app(
        self,
        plugin_id: str,
        asgi_app: Any,
        *,
        prefix: str,
        name: Optional[str] = None,
    ) -> None:
        """Mount a plugin-owned ASGI application below ``/api``."""
        http_app = self._plugin_http_app
        if http_app is None:
            raise RuntimeError(
                "Cannot register plugin ASGI app: FastAPI app was not "
                "configured (internal setup error).",
            )
        normalized = self._normalize_http_prefix(prefix)
        if normalized in self._http_prefix_to_plugin:
            owner = self._http_prefix_to_plugin[normalized]
            raise ValueError(
                f"Plugin HTTP prefix '{normalized}' is already registered "
                f"by plugin '{owner}'",
            )

        routes = http_app.router.routes
        spa_idx = _find_console_spa_route_index(http_app)
        http_app.mount(
            f"/api{normalized}",
            asgi_app,
            name=name or f"plugin:{plugin_id}",
        )
        route = routes.pop()
        if spa_idx is None:
            routes.append(route)
        else:
            routes.insert(spa_idx, route)
        http_app.openapi_schema = None
        self._asgi_app_registrations.append(
            AsgiAppRegistration(plugin_id, normalized, route),
        )
        self._http_prefix_to_plugin[normalized] = plugin_id

    def register_public_http_route(
        self,
        plugin_id: str,
        *,
        method: str,
        path: str,
    ) -> None:
        """Declare one exact plugin-owned route as anonymously readable.

        This registration only changes the outer authentication decision. The
        plugin still owns the route implementation and its response contract.
        Wildcards, prefixes, query strings, and unsafe methods are rejected.
        """
        normalized_method = str(method).strip().upper()
        if normalized_method not in {"GET", "HEAD"}:
            raise ValueError("Public plugin HTTP routes must use GET or HEAD")
        normalized_path = str(path).strip()
        if (
            not normalized_path.startswith("/api/")
            or normalized_path.endswith("/")
            or "?" in normalized_path
            or "#" in normalized_path
            or "{" in normalized_path
            or "}" in normalized_path
            or "//" in normalized_path
        ):
            raise ValueError(
                "Public plugin HTTP route must be one exact /api/... path",
            )
        key = (normalized_method, normalized_path)
        existing = self._public_http_routes.get(key)
        if existing is not None:
            raise ValueError(
                f"Public HTTP route {normalized_method} {normalized_path!r} "
                f"is already registered by plugin '{existing.plugin_id}'",
            )
        self._public_http_routes[key] = PublicHttpRouteRegistration(
            plugin_id=plugin_id,
            method=normalized_method,
            path=normalized_path,
        )

    def is_public_http_route(self, method: str, path: str) -> bool:
        """Return whether a plugin declared this exact method/path public."""
        normalized_method = str(method).strip().upper()
        if normalized_method == "HEAD":
            return ("HEAD", path) in self._public_http_routes or (
                "GET",
                path,
            ) in self._public_http_routes
        return (normalized_method, path) in self._public_http_routes

    def get_public_http_routes(self) -> List[PublicHttpRouteRegistration]:
        """Return public route declarations for diagnostics and tests."""
        return list(self._public_http_routes.values())

    def register_platform_capability(
        self,
        plugin_id: str,
        capability_id: str,
        contract_version: str,
        group: str,
        dependencies: tuple[str, ...] = (),
    ) -> None:
        """Publish a versioned capability through the generic plugin SPI."""
        if capability_id in self._platform_capabilities:
            owner = self._platform_capabilities[capability_id].plugin_id
            raise ValueError(
                f"Platform capability '{capability_id}' is already registered "
                f"by plugin '{owner}'",
            )
        self._platform_capabilities[
            capability_id
        ] = PlatformCapabilityRegistration(
            plugin_id=plugin_id,
            capability_id=capability_id,
            contract_version=contract_version,
            group=group,
            dependencies=tuple(dependencies),
        )

    def get_platform_capabilities(
        self,
    ) -> Dict[str, PlatformCapabilityRegistration]:
        return self._platform_capabilities.copy()

    def register_workspace_context_enricher(
        self,
        plugin_id: str,
        name: str,
        callback: Callable,
        priority: int = 100,
    ) -> None:
        """Register a callback that may add trusted runtime-only context."""
        if any(
            item.plugin_id == plugin_id and item.name == name
            for item in self._workspace_context_enrichers
        ):
            raise ValueError(
                f"Workspace context enricher '{name}' is already registered "
                f"by plugin '{plugin_id}'",
            )
        self._workspace_context_enrichers.append(
            WorkspaceContextEnricherRegistration(
                plugin_id=plugin_id,
                name=name,
                callback=callback,
                priority=priority,
            ),
        )
        self._workspace_context_enrichers.sort(key=lambda item: item.priority)

    def get_workspace_context_enrichers(
        self,
    ) -> List[WorkspaceContextEnricherRegistration]:
        return list(self._workspace_context_enrichers)

    def register_workspace_turn_handler(
        self,
        plugin_id: str,
        capability_id: str,
        callback: Callable,
    ) -> None:
        if capability_id in self._workspace_turn_handlers:
            owner = self._workspace_turn_handlers[capability_id].plugin_id
            raise ValueError(
                f"Workspace turn handler '{capability_id}' is already "
                f"registered by plugin '{owner}'",
            )
        self._workspace_turn_handlers[
            capability_id
        ] = WorkspaceTurnHandlerRegistration(
            plugin_id=plugin_id,
            capability_id=capability_id,
            callback=callback,
        )

    def get_workspace_turn_handler(
        self,
        capability_id: str,
    ) -> WorkspaceTurnHandlerRegistration | None:
        return self._workspace_turn_handlers.get(capability_id)

    def register_aigc_event_consumer_factory(
        self,
        plugin_id: str,
        name: str,
        factory: Callable,
    ) -> None:
        if any(
            item.name == name for item in self._aigc_event_consumer_factories
        ):
            raise ValueError(
                f"AIGC event consumer factory already exists: {name}",
            )
        self._aigc_event_consumer_factories.append(
            AigcEventConsumerFactoryRegistration(plugin_id, name, factory),
        )

    def get_aigc_event_consumer_factories(
        self,
    ) -> List[AigcEventConsumerFactoryRegistration]:
        return list(self._aigc_event_consumer_factories)

    def register_aigc_canvas_policy(
        self,
        plugin_id: str,
        name: str,
        callback: Callable,
    ) -> None:
        if any(item.name == name for item in self._aigc_canvas_policies):
            raise ValueError(f"AIGC canvas policy already exists: {name}")
        self._aigc_canvas_policies.append(
            AigcCanvasPolicyRegistration(plugin_id, name, callback),
        )

    def get_aigc_canvas_policies(self) -> List[AigcCanvasPolicyRegistration]:
        return list(self._aigc_canvas_policies)

    def register_sealed_package_type(
        self,
        plugin_id: str,
        package_type: str,
        handler: Any,
    ) -> None:
        if package_type in self._sealed_package_types:
            owner = self._sealed_package_types[package_type].plugin_id
            raise ValueError(
                f"Sealed package type '{package_type}' is already registered "
                f"by plugin '{owner}'",
            )
        self._sealed_package_types[
            package_type
        ] = SealedPackageTypeRegistration(
            plugin_id=plugin_id,
            package_type=package_type,
            handler=handler,
        )

    def get_sealed_package_type(
        self,
        package_type: str,
    ) -> SealedPackageTypeRegistration | None:
        return self._sealed_package_types.get(package_type)

    def get_sealed_package_types(
        self,
    ) -> Dict[str, SealedPackageTypeRegistration]:
        return self._sealed_package_types.copy()

    def sealed_package_type_supports(
        self,
        package_type: str,
        feature: str,
    ) -> bool:
        registration = self.get_sealed_package_type(package_type)
        supports = (
            getattr(registration.handler, "supports_runtime_feature", None)
            if registration is not None
            else None
        )
        return bool(callable(supports) and supports(feature))

    async def enrich_workspace_context(
        self,
        context: Mapping[str, Any],
        *,
        granted_capabilities: Mapping[str, str],
        invocation_id: str,
    ) -> dict[str, Any]:
        """Run trusted context enrichers in deterministic priority order."""
        import inspect

        current = dict(context)
        for registration in self._workspace_context_enrichers:
            result = registration.callback(
                current,
                granted_capabilities=granted_capabilities,
                invocation_id=invocation_id,
            )
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, Mapping):
                raise TypeError(
                    "Workspace context enricher must return a mapping: "
                    f"{registration.plugin_id}:{registration.name}",
                )
            current = dict(result)
        return current

    def _unregister_plugin_http_routes(self, plugin_id: str) -> None:
        self._public_http_routes = {
            key: registration
            for key, registration in self._public_http_routes.items()
            if registration.plugin_id != plugin_id
        }
        http_app = self._plugin_http_app
        if http_app is None:
            return

        to_drop = [
            reg
            for reg in self._http_router_registrations
            if reg.plugin_id == plugin_id
        ]
        routes = http_app.router.routes
        for reg in to_drop:
            self._http_prefix_to_plugin.pop(reg.prefix, None)
            for route in reg.routes:
                try:
                    routes.remove(route)
                except ValueError:
                    logger.warning(
                        "Could not remove plugin HTTP route %r for '%s' "
                        "(already removed?)",
                        getattr(route, "path", route),
                        plugin_id,
                    )

        self._http_router_registrations = [
            r
            for r in self._http_router_registrations
            if r.plugin_id != plugin_id
        ]
        asgi_to_drop = [
            reg
            for reg in self._asgi_app_registrations
            if reg.plugin_id == plugin_id
        ]
        for reg in asgi_to_drop:
            self._http_prefix_to_plugin.pop(reg.prefix, None)
            try:
                routes.remove(reg.route)
            except ValueError:
                logger.warning(
                    "Could not remove plugin ASGI mount %r for '%s'",
                    reg.prefix,
                    plugin_id,
                )
        self._asgi_app_registrations = [
            reg
            for reg in self._asgi_app_registrations
            if reg.plugin_id != plugin_id
        ]
        http_app.openapi_schema = None

    def register_provider(
        self,
        plugin_id: str,
        provider_id: str,
        provider_class: Type,
        label: str,
        base_url: str,
        metadata: Dict[str, Any],
    ):
        """Register a provider.

        Args:
            plugin_id: Plugin identifier
            provider_id: Provider identifier
            provider_class: Provider class
            label: Display label
            base_url: API base URL
            metadata: Additional metadata

        Raises:
            ValueError: If provider_id already registered
        """
        if provider_id in self._providers:
            existing = self._providers[provider_id]
            raise ValueError(
                f"Provider '{provider_id}' already registered "
                f"by plugin '{existing.plugin_id}'",
            )

        self._providers[provider_id] = ProviderRegistration(
            plugin_id=plugin_id,
            provider_id=provider_id,
            provider_class=provider_class,
            label=label,
            base_url=base_url,
            metadata=metadata,
        )
        logger.info(
            f"Registered provider '{provider_id}' from plugin '{plugin_id}'",
        )

    def get_provider(self, provider_id: str) -> Optional[ProviderRegistration]:
        """Get provider registration.

        Args:
            provider_id: Provider identifier

        Returns:
            ProviderRegistration or None if not found
        """
        return self._providers.get(provider_id)

    def get_all_providers(self) -> Dict[str, ProviderRegistration]:
        """Get all provider registrations.

        Returns:
            Dictionary of provider_id -> ProviderRegistration
        """
        return self._providers.copy()

    def set_runtime_helpers(self, helpers):
        """Set runtime helpers.

        Args:
            helpers: RuntimeHelpers instance
        """
        self._runtime_helpers = helpers

    def get_runtime_helpers(self):
        """Get runtime helpers.

        Returns:
            RuntimeHelpers instance or None
        """
        return self._runtime_helpers

    def register_startup_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a startup hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._startup_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._startup_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered startup hook '{hook_name}' from plugin '{plugin_id}' "
            f"(priority={priority})",
        )

    def register_shutdown_hook(
        self,
        plugin_id: str,
        hook_name: str,
        callback: Callable,
        priority: int = 100,
    ):
        """Register a shutdown hook.

        Args:
            plugin_id: Plugin identifier
            hook_name: Hook name
            callback: Callback function
            priority: Priority (lower = earlier execution)
        """
        hook = HookRegistration(
            plugin_id=plugin_id,
            hook_name=hook_name,
            callback=callback,
            priority=priority,
        )
        self._shutdown_hooks.append(hook)
        # Sort by priority (lower = earlier)
        self._shutdown_hooks.sort(key=lambda h: h.priority)
        logger.info(
            f"Registered shutdown hook '{hook_name}' from plugin "
            f"'{plugin_id}' (priority={priority})",
        )

    def get_startup_hooks(self) -> List[HookRegistration]:
        """Get all startup hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._startup_hooks.copy()

    def get_shutdown_hooks(self) -> List[HookRegistration]:
        """Get all shutdown hooks sorted by priority.

        Returns:
            List of HookRegistration
        """
        return self._shutdown_hooks.copy()

    def register_control_command(
        self,
        plugin_id: str,
        handler: Any,
        priority_level: int = 10,
    ):
        """Register a control command handler.

        Args:
            plugin_id: Plugin identifier
            handler: Control command handler instance
            priority_level: Command priority (default: 10 = high)
        """
        cmd_reg = ControlCommandRegistration(
            plugin_id=plugin_id,
            handler=handler,
            priority_level=priority_level,
        )
        self._control_commands.append(cmd_reg)
        logger.info(
            f"Registered control command '{handler.command_name}' "
            f"from plugin '{plugin_id}' (priority={priority_level})",
        )

    def get_control_commands(self) -> List[ControlCommandRegistration]:
        """Get all registered control command handlers.

        Returns:
            List of ControlCommandRegistration
        """
        return self._control_commands.copy()

    def register_plugin_manifest(
        self,
        plugin_id: str,
        manifest: Dict[str, Any],
    ):
        """Register plugin manifest.

        Args:
            plugin_id: Plugin identifier
            manifest: Plugin manifest dictionary
        """
        self._plugin_manifests[plugin_id] = manifest
        logger.debug(f"Registered manifest for plugin '{plugin_id}'")

    def get_all_plugin_manifests(self) -> Dict[str, Dict[str, Any]]:
        """Get all plugin manifests.

        Returns:
            Dictionary of plugin_id -> manifest
        """
        return self._plugin_manifests.copy()

    def get_plugin_manifest(
        self,
        plugin_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get plugin manifest.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin manifest dict or None
        """
        return self._plugin_manifests.get(plugin_id)

    def unregister_plugin(self, plugin_id: str) -> None:
        """Remove all in-memory registrations for a plugin.

        Clears manifest, providers, hooks, and control commands
        that were registered under the given plugin_id.  Does not
        touch disk or agent configurations.

        Args:
            plugin_id: Plugin identifier to remove
        """
        self._unregister_plugin_http_routes(plugin_id)

        self._plugin_manifests.pop(plugin_id, None)

        providers_to_remove = [
            pid
            for pid, reg in self._providers.items()
            if reg.plugin_id == plugin_id
        ]
        for pid in providers_to_remove:
            del self._providers[pid]
            logger.info(
                f"Unregistered provider '{pid}' " f"for plugin '{plugin_id}'",
            )

        self._startup_hooks = [
            h for h in self._startup_hooks if h.plugin_id != plugin_id
        ]
        self._shutdown_hooks = [
            h for h in self._shutdown_hooks if h.plugin_id != plugin_id
        ]
        self._control_commands = [
            c for c in self._control_commands if c.plugin_id != plugin_id
        ]
        self._platform_capabilities = {
            capability_id: registration
            for capability_id, registration in self._platform_capabilities.items()
            if registration.plugin_id != plugin_id
        }
        self._workspace_context_enrichers = [
            item
            for item in self._workspace_context_enrichers
            if item.plugin_id != plugin_id
        ]
        self._workspace_turn_handlers = {
            capability_id: item
            for capability_id, item in self._workspace_turn_handlers.items()
            if item.plugin_id != plugin_id
        }
        self._aigc_event_consumer_factories = [
            item
            for item in self._aigc_event_consumer_factories
            if item.plugin_id != plugin_id
        ]
        self._aigc_canvas_policies = [
            item
            for item in self._aigc_canvas_policies
            if item.plugin_id != plugin_id
        ]
        self._sealed_package_types = {
            package_type: item
            for package_type, item in self._sealed_package_types.items()
            if item.plugin_id != plugin_id
        }
        logger.info(
            f"Unregistered all entries for plugin '{plugin_id}'",
        )

    def get_plugin_id_for_tool(self, tool_name: str) -> Optional[str]:
        """Get plugin ID that provides a specific tool.

        Args:
            tool_name: Tool function name

        Returns:
            Plugin ID or None
        """
        for plugin_id, manifest in self._plugin_manifests.items():
            meta = manifest.get("meta", {})
            # Check old format: meta.tool_name
            if meta.get("tool_name") == tool_name:
                return plugin_id
            # Check new format: meta.tools array
            tools = meta.get("tools", [])
            if isinstance(tools, list):
                for tool in tools:
                    if (
                        isinstance(tool, dict)
                        and tool.get("name") == tool_name
                    ):
                        return plugin_id
        return None

    def get_tool_config(
        self,
        tool_name: str,
        agent_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get tool configuration for a specific agent.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier

        Returns:
            Tool configuration dict or None
        """
        try:
            from ..config.config import load_agent_config

            agent_config = load_agent_config(agent_id)
            if (
                not agent_config.tools
                or tool_name not in agent_config.tools.builtin_tools
            ):
                return None

            tool_config = agent_config.tools.builtin_tools[tool_name]
            return tool_config.config if tool_config.config else None
        except Exception as e:
            logger.error(f"Failed to load tool config: {e}")
            return None

    def set_tool_config(
        self,
        tool_name: str,
        agent_id: str,
        config: Dict[str, Any],
    ) -> None:
        """Save tool configuration for a specific agent.

        Args:
            tool_name: Tool function name
            agent_id: Agent identifier
            config: Configuration data
        """
        try:
            from ..config.config import (
                load_agent_config,
                save_agent_config,
            )

            agent_config = load_agent_config(agent_id)
            if (
                not agent_config.tools
                or tool_name not in agent_config.tools.builtin_tools
            ):
                raise ValueError(f"Tool '{tool_name}' not found in agent")

            # Update tool config
            agent_config.tools.builtin_tools[tool_name].config = config

            # Save agent config
            save_agent_config(agent_id, agent_config)

            logger.info(
                f"Saved config for tool '{tool_name}' in agent '{agent_id}'",
            )
        except Exception as e:
            logger.error(f"Failed to save tool config: {e}")
            raise
