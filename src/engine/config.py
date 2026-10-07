"""Configuration loader — reads runtime config from Azure App Configuration.

Terraform writes the configuration keys (see infra/modules/app_config):

    pwrsched:resourceTypes        JSON array  -> enabled handler keys
    pwrsched:scopes:include       JSON array  -> include scopes
    pwrsched:scopes:exclude       JSON array  -> exclude scopes
    pwrsched:dryRun               "true"/"false"
    pwrsched:maxActionsPerRun     integer string
    pwrsched:reconcileSchedule    NCRONTAB string
    pwrsched:profiles:<name>      JSON profile document (§6.2)

This module reads those keys and parses them into a :class:`Settings` object and
a set of :class:`~engine.evaluator.Profile` objects, exposing a
``profile_provider(name) -> Profile | None`` for the engine (BR-005 returns None
for unknown profiles).

The App Configuration client is injected (``list_fn``) so the parsing is fully
unit-testable without the Azure SDK. ``load_from_app_configuration`` provides the
real wiring using azure-appconfiguration + azure-identity (managed identity).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional

from .evaluator import Profile, ProfileError, parse_profile

__all__ = [
    "Settings",
    "LoadedConfig",
    "parse_config",
    "load_from_app_configuration",
]

logger = logging.getLogger("pwrsched.config")

KEY_RESOURCE_TYPES = "pwrsched:resourceTypes"
KEY_SCOPES_INCLUDE = "pwrsched:scopes:include"
KEY_SCOPES_EXCLUDE = "pwrsched:scopes:exclude"
KEY_DRY_RUN = "pwrsched:dryRun"
KEY_MAX_ACTIONS = "pwrsched:maxActionsPerRun"
KEY_MAX_PARALLEL = "pwrsched:maxParallelActions"
KEY_LOG_CONVERGED = "pwrsched:logConvergedDecisions"
KEY_SCHEDULE = "pwrsched:reconcileSchedule"
PROFILE_PREFIX = "pwrsched:profiles:"


@dataclass(frozen=True)
class Settings:
    """Global settings parsed from App Configuration (§6.3)."""

    enabled_resource_types: list[str] = field(default_factory=list)
    include_scopes: list[str] = field(default_factory=list)
    exclude_scopes: list[str] = field(default_factory=list)
    dry_run: bool = True
    max_actions_per_run: int = 200
    # SC-01 (FR-034): bound on parallel start/stop submissions per order group.
    max_parallel_actions: int = 10
    # SC-04 (NFR-011): emit per-resource already-converged decision records.
    log_converged_decisions: bool = True
    reconcile_schedule: str = "0 */15 * * * *"


@dataclass
class LoadedConfig:
    """Parsed configuration: settings + profiles + a profile_provider."""

    settings: Settings
    profiles: dict[str, Profile]

    def profile_provider(self, name: str) -> Optional[Profile]:
        """Return the named profile or None if undefined (BR-005)."""
        return self.profiles.get(name)


def _as_bool(value: Optional[str], default: bool = True) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"true", "1", "yes"}


def _as_int(value: Optional[str], default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        logger.warning("pwrsched.config: value is not valid JSON array: %r", value)
        return []
    return [str(x) for x in parsed] if isinstance(parsed, list) else []


def parse_config(kv: Mapping[str, str]) -> LoadedConfig:
    """Parse a flat key→value mapping (as returned by App Configuration).

    Invalid profile documents are logged and skipped (so one bad profile does
    not break the whole cycle); the engine treats a missing profile as BR-005.
    """
    settings = Settings(
        enabled_resource_types=_as_list(kv.get(KEY_RESOURCE_TYPES)),
        include_scopes=_as_list(kv.get(KEY_SCOPES_INCLUDE)),
        exclude_scopes=_as_list(kv.get(KEY_SCOPES_EXCLUDE)),
        dry_run=_as_bool(kv.get(KEY_DRY_RUN), default=True),
        max_actions_per_run=_as_int(kv.get(KEY_MAX_ACTIONS), default=200),
        max_parallel_actions=_as_int(kv.get(KEY_MAX_PARALLEL), default=10),
        log_converged_decisions=_as_bool(kv.get(KEY_LOG_CONVERGED), default=True),
        reconcile_schedule=kv.get(KEY_SCHEDULE) or "0 */15 * * * *",
    )

    profiles: dict[str, Profile] = {}
    for key, value in kv.items():
        if not key.startswith(PROFILE_PREFIX):
            continue
        name = key[len(PROFILE_PREFIX):]
        try:
            raw = json.loads(value)
            profiles[name] = parse_profile(name, raw)
        except (ValueError, ProfileError) as exc:
            logger.warning("pwrsched.config: skipping invalid profile %r: %s", name, exc)

    logger.info(
        "pwrsched.config: loaded %d profile(s), %d enabled type(s), dryRun=%s",
        len(profiles), len(settings.enabled_resource_types), settings.dry_run,
    )
    return LoadedConfig(settings=settings, profiles=profiles)


def load_from_app_configuration(
    endpoint: str,
    *,
    credential=None,
    list_fn: Optional[Callable[[], Iterable[Mapping[str, str]]]] = None,
) -> LoadedConfig:
    """Load configuration from App Configuration using a managed identity.

    Args:
        endpoint: App Configuration data-plane endpoint (``APP_CONFIG_ENDPOINT``).
        credential: Optional token credential; defaults to DefaultAzureCredential
            which uses the user-assigned managed identity (via AZURE_CLIENT_ID).
        list_fn: Optional override returning an iterable of objects with ``.key``
            and ``.value`` — used by tests to avoid the Azure SDK.

    Returns:
        A LoadedConfig.
    """
    if list_fn is None:
        # Imported lazily so unit tests never require the Azure SDK.
        from azure.appconfiguration import AzureAppConfigurationClient
        from azure.identity import DefaultAzureCredential

        cred = credential or DefaultAzureCredential()
        client = AzureAppConfigurationClient(base_url=endpoint, credential=cred)

        def list_fn():  # type: ignore[misc]
            # key_filter "pwrsched:*" scopes the read to our keys only.
            return client.list_configuration_settings(key_filter="pwrsched:*")

    kv: dict[str, str] = {}
    for setting in list_fn():
        key = getattr(setting, "key", None)
        value = getattr(setting, "value", None)
        if isinstance(key, str):
            kv[key] = value if value is not None else ""
    return parse_config(kv)
