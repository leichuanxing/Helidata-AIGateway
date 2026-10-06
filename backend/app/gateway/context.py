from dataclasses import dataclass, field
from time import monotonic
from datetime import datetime,timezone


@dataclass
class GatewayContext:
    request_id: str
    operation: str
    logical_model: str | None = None
    payload: dict | None = None
    original_model: str | None = None
    route_group_id: int | None = None
    route_config_id: int | None = None
    first_effective: float | None = None
    generation_end: float | None = None
    generation_start: float | None = None
    stream_chunks: int = 0
    client_ip: str = ''
    provider_lease_lost: bool = False
    lease_error: str | None = None
    admission: object = None
    request: object = None
    quota_usage: int | None = None
    usage_snapshot: dict = field(default_factory=dict)
    upstream_started: float | None = None
    upstream_elapsed_ms: float | None = None
    terminal_written: bool = False
    response_status: int = 200
    error_message: str | None = None
    received_at: datetime = field(default_factory=lambda:datetime.now(timezone.utc))
    authorized_groups: list = field(default_factory=list)
    attempts: list = field(default_factory=list)
    attempt_started: float = field(default_factory=monotonic)
    key: object = None
    user: object = None
    group: object = None
    candidates: list = field(default_factory=list)
    mapping: object = None
    provider: object = None
    adapter: object = None
    stages: list[str] = field(default_factory=list)
    deferred: dict = field(default_factory=dict)
    started: float = field(default_factory=monotonic)
