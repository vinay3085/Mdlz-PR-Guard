import hashlib
from typing import List
from sqlalchemy.orm import Session
from app.models.database import Finding
from app.repositories.base import BaseRepository
from app.services.interfaces import LLMFinding, PolicyViolation, StaticFinding


class FindingsRepository(BaseRepository[Finding]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Finding)

    def _dedupe_hash(self, *parts: str) -> str:
        content = ":".join(str(p) for p in parts)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def bulk_insert_static(self, pr_review_id: int, findings: List[StaticFinding]) -> None:
        for f in findings:
            self._session.add(
                Finding(
                    pr_review_id=pr_review_id,
                    source=f.source,
                    severity=f.severity,
                    rule_id=f.rule_id,
                    file_path=f.file_path,
                    line_number=f.line_number,
                    message=f.message,
                    code_snippet=(f.code_snippet or "")[:500],
                    dedupe_hash=self._dedupe_hash(
                        f.source, f.rule_id, f.file_path, str(f.line_number), f.message
                    ),
                )
            )
        self._session.flush()

    def bulk_insert_policy(self, pr_review_id: int, violations: List[PolicyViolation]) -> None:
        for v in violations:
            self._session.add(
                Finding(
                    pr_review_id=pr_review_id,
                    source="policy",
                    severity=v.severity,
                    rule_id=v.rule_id,
                    file_path=v.file_path,
                    line_number=v.line_number,
                    message=v.message,
                    dedupe_hash=self._dedupe_hash(
                        "policy", v.rule_id, str(v.file_path or ""), str(v.line_number or 0), v.message
                    ),
                )
            )
        self._session.flush()

    def bulk_insert_llm(self, pr_review_id: int, findings: List[LLMFinding]) -> None:
        for f in findings:
            self._session.add(
                Finding(
                    pr_review_id=pr_review_id,
                    source="llm",
                    severity=f.severity,
                    rule_id="llm.finding",
                    file_path=f.file_path,
                    line_number=f.line_number,
                    message=f.message,
                    dedupe_hash=self._dedupe_hash(
                        "llm", str(f.file_path or ""), str(f.line_number or 0), f.message
                    ),
                )
            )
        self._session.flush()
