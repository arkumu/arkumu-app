from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin


GUIDED_STEPS: List[str] = [
    "project",
    "events",
    "actors",
    "digital_objects",
    "summary",
]


@dataclass
class FlowEntity:
    uri: str
    dataset: str
    label: str
    anchor_values: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FlowEntity":
        return cls(
            uri=data.get("uri", ""),
            dataset=data.get("dataset", ""),
            label=data.get("label", ""),
            anchor_values=dict(data.get("anchor_values", {})),
        )


@dataclass
class FlowEvent(FlowEntity):
    actors: List[FlowEntity] = field(default_factory=list)
    digital_objects: List[FlowEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        payload = super().to_dict()
        payload["actors"] = [actor.to_dict() for actor in self.actors]
        payload["digital_objects"] = [obj.to_dict() for obj in self.digital_objects]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FlowEvent":
        base = FlowEntity.from_dict(data)
        actors = [
            FlowEntity.from_dict(actor) for actor in data.get("actors", [])
        ]
        digital_objects = [
            FlowEntity.from_dict(obj) for obj in data.get("digital_objects", [])
        ]
        return cls(
            uri=base.uri,
            dataset=base.dataset,
            label=base.label,
            anchor_values=base.anchor_values,
            actors=actors,
            digital_objects=digital_objects,
        )


@dataclass
class FlowState:
    flow_id: str
    mapping_id: str
    project: Optional[FlowEntity] = None
    events: Dict[str, FlowEvent] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "flow_id": self.flow_id,
            "mapping_id": self.mapping_id,
            "project": self.project.to_dict() if self.project else None,
            "events": {uri: event.to_dict() for uri, event in self.events.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "FlowState":
        project_data = data.get("project")
        events_data = data.get("events", {})
        return cls(
            flow_id=data.get("flow_id", ""),
            mapping_id=data.get("mapping_id", ""),
            project=FlowEntity.from_dict(project_data) if project_data else None,
            events={
                uri: FlowEvent.from_dict(event_data)
                for uri, event_data in events_data.items()
            },
        )

    def reset_after_project_change(self) -> None:
        """Clear downstream selections when the project changes."""
        self.events.clear()


class SchemaWorkspaceCoordinator(BaseCoordinatorMixin):
    """
    Flow state coordinator built on the shared BaseCoordinatorMixin.

    Stores workspace flow state per organization and mapping in the user session
    while reusing the standardized session key handling provided by the base mixin.
    """

    FLOW_SESSION_BASE_KEY = "schema_workspace_flows"

    # ------------------------------------------------------------------ #
    # Session helpers
    # ------------------------------------------------------------------ #
    def _session_key(self, organization) -> str:
        org_id = getattr(organization, "id", None)
        return self.get_session_key(self.FLOW_SESSION_BASE_KEY, org_id)

    def _load_mapping_store(
        self, request, mapping, organization
    ) -> Tuple[str, Dict[str, object], str, Dict[str, Dict[str, object]]]:
        session_key = self._session_key(organization)
        root_store: Dict[str, object] = request.session.get(session_key, {})
        mapping_key = str(mapping.id)
        mapping_store: Dict[str, Dict[str, object]] = root_store.get(mapping_key, {})
        return session_key, root_store, mapping_key, mapping_store

    def _persist_mapping_store(
        self,
        request,
        session_key: str,
        root_store: Dict[str, object],
        mapping_key: str,
        mapping_store: Dict[str, Dict[str, object]],
    ) -> None:
        new_root = dict(root_store)
        new_root[mapping_key] = mapping_store
        request.session[session_key] = new_root
        request.session.modified = True

    # ------------------------------------------------------------------ #
    # Flow state management
    # ------------------------------------------------------------------ #
    def get_or_create_flow_state(
        self,
        request,
        mapping,
        organization,
        flow_id: Optional[str] = None,
    ) -> FlowState:
        session_key, root_store, mapping_key, mapping_store = self._load_mapping_store(
            request, mapping, organization
        )

        if flow_id and flow_id in mapping_store:
            return FlowState.from_dict(mapping_store[flow_id])

        if flow_id and flow_id not in mapping_store:
            mapping_store = dict(mapping_store)
            state = FlowState(flow_id=flow_id, mapping_id=str(mapping.id))
            mapping_store[state.flow_id] = state.to_dict()
            self._persist_mapping_store(
                request, session_key, root_store, mapping_key, mapping_store
            )
            return state

        if mapping_store:
            first_flow_id = next(iter(mapping_store))
            return FlowState.from_dict(mapping_store[first_flow_id])

        return self._create_flow_state(
            request=request,
            session_key=session_key,
            root_store=root_store,
            mapping_key=mapping_key,
            mapping=mapping,
            preferred_flow_id=flow_id,
        )

    def _create_flow_state(
        self,
        *,
        request,
        session_key: str,
        root_store: Dict[str, object],
        mapping_key: str,
        mapping,
        preferred_flow_id: Optional[str] = None,
    ) -> FlowState:
        flow_id = preferred_flow_id or uuid4().hex
        state = FlowState(flow_id=flow_id, mapping_id=str(mapping.id))
        mapping_store: Dict[str, Dict[str, object]] = {state.flow_id: state.to_dict()}
        self._persist_mapping_store(
            request, session_key, root_store, mapping_key, mapping_store
        )
        return state

    def save_flow_state(
        self,
        request,
        mapping,
        organization,
        state: FlowState,
    ) -> None:
        session_key, root_store, mapping_key, mapping_store = self._load_mapping_store(
            request, mapping, organization
        )
        mapping_store = dict(mapping_store)
        mapping_store[state.flow_id] = state.to_dict()
        self._persist_mapping_store(
            request, session_key, root_store, mapping_key, mapping_store
        )

    def delete_flow_state(
        self,
        request,
        mapping,
        organization,
        flow_id: str,
    ) -> None:
        session_key, root_store, mapping_key, mapping_store = self._load_mapping_store(
            request, mapping, organization
        )
        if flow_id not in mapping_store:
            return
        mapping_store = dict(mapping_store)
        mapping_store.pop(flow_id, None)
        self._persist_mapping_store(
            request, session_key, root_store, mapping_key, mapping_store
        )

    def load_flow_state(
        self,
        request,
        mapping,
        organization,
        flow_id: str,
    ) -> Optional[FlowState]:
        _, _, _, mapping_store = self._load_mapping_store(request, mapping, organization)
        data = mapping_store.get(flow_id)
        if not data:
            return None
        return FlowState.from_dict(data)

    def list_flow_states(
        self,
        request,
        mapping,
        organization,
    ) -> Dict[str, FlowState]:
        _, _, _, mapping_store = self._load_mapping_store(request, mapping, organization)
        return {
            flow_id: FlowState.from_dict(payload)
            for flow_id, payload in mapping_store.items()
        }

    def iter_flow_states(
        self,
        request,
        mapping,
        organization,
    ) -> Iterable[FlowState]:
        return self.list_flow_states(request, mapping, organization).values()

    def reset_mapping_flows(self, request, mapping, organization) -> None:
        session_key, root_store, mapping_key, mapping_store = self._load_mapping_store(
            request, mapping, organization
        )
        if not mapping_store:
            return
        root_store = dict(root_store)
        root_store.pop(mapping_key, None)
        request.session[session_key] = root_store
        request.session.modified = True
