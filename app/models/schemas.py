from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class WebhookResponse(BaseModel):
    status: str


class FindingSchema(BaseModel):
    id: int
    source: str
    severity: str
    rule_id: Optional[str]
    file_path: Optional[str]
    line_number: Optional[int]
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PRReviewSchema(BaseModel):
    id: int
    repo_full_name: str
    pr_number: int
    head_sha: str
    status: str
    total_findings: int
    critical_count: int
    high_count: int
    latency_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]
    findings: List[FindingSchema] = []

    model_config = {"from_attributes": True}


class UsageSummary(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float
    latency_ms: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}
