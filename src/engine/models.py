"""Shared data model for the reconciliation engine.

These dataclasses are the common currency passed between the engine stages:
discovery (T-201) -> selection (T-202) -> ordering (T-203) -> reconcile (T-204).
They carry no Azure SDK types so the pipeline stays unit-testable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional

__all__ = [
    "ActualState",
    "ActionType",
    "ResourceRecord",
    "PlannedAction",
]


class ActualState(str, Enum):
    """Normalised actual power state reported by a handler.

    TRANSITIONAL covers Starting/Stopping/Updating; the engine skips these and
    retries next cycle (FR-033). UNKNOWN means the handler could not determine
    the state and the resource is skipped and logged.
    """

    RUNNING = "Running"
    STOPPED = "Stopped"
    TRANSITIONAL = "Transitional"
    UNKNOWN = "Unknown"


class ActionType(str, Enum):
    START = "start"
    STOP = "stop"
    NONE = "none"


@dataclass(frozen=True)
class ResourceRecord:
    """A resource discovered via Resource Graph, normalised for the engine.

    Attributes:
        resource_id: Full ARM resource ID.
        resource_type: ARM type, e.g. 'Microsoft.Compute/virtualMachines'.
        handler_key: Engine handler key, e.g. 'vm' (resolved from resource_type).
        subscription_id: Owning subscription GUID.
        resource_group: Owning resource group name.
        location: Azure region.
        tags: Effective tags already resolved with precedence
            resource > resource group > subscription (FR-013). In discovery
            this holds the resource's own tags; selection merges the rest.
        subscription_tags: Tags on the owning subscription (for BR-003 prod check).
        resource_group_tags: Tags on the owning resource group.
    """

    resource_id: str
    resource_type: str
    handler_key: str
    subscription_id: str
    resource_group: str
    location: str = ""
    tags: Mapping[str, str] = field(default_factory=dict)
    subscription_tags: Mapping[str, str] = field(default_factory=dict)
    resource_group_tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedAction:
    """An intended start/stop decision for a single resource.

    Produced by selection+evaluation, ordered by T-203 and executed by T-204.
    ``actual_state`` is the normalised observed state at planning time (for the
    OBS-001 decision log); ``result`` is set at execution time
    (e.g. 'submitted', 'dry-run', 'failed', 'skipped', 'no-action').
    """

    resource: ResourceRecord
    action: ActionType
    desired_state: str
    reason: str
    profile_name: Optional[str] = None
    order: int = 3
    warning: Optional[str] = None
    actual_state: str = "Unknown"
    result: str = ""
