from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ConnectorHealth(BaseModel):
    connector_code: str = 'mapsearch'
    version: str = '1'
    status: str
    capabilities: list[str]


class ConnectorTaskSummary(BaseModel):
    task_id: str
    status: str
    total_work_units: int
    completed_work_units: int
    verified_lead_count: int
    delivery_enabled: bool


class ConnectorTaskList(BaseModel):
    items: list[ConnectorTaskSummary]


class ConnectorResultItem(BaseModel):
    company_name: str
    city: str
    address: str | None = None
    contact: str
    evidence_url: str | None = None
    verification_status: str = 'amap_collected'


class ConnectorTaskResults(BaseModel):
    task_id: str
    status: str
    items: list[ConnectorResultItem]


class ConnectorSearchResponse(BaseModel):
    mode: Literal['cached', 'task']
    task_id: str | None = None
    status: str
    items: list[ConnectorResultItem] = Field(default_factory=list)


class ConnectorCreateTaskRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=4000)
    models: list[str] = Field(default_factory=list, max_length=10)

    @field_validator('models')
    @classmethod
    def clean_models(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))


class ConnectorSearchRequest(ConnectorCreateTaskRequest):
    """A user-facing search that consumes cached results before queuing work."""
