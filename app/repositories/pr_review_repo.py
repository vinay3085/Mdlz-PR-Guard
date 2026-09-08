from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models.database import PRReview
from app.repositories.base import BaseRepository


class PRReviewRepository(BaseRepository[PRReview]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, PRReview)

    def get_by_sha(self, repo_full_name: str, head_sha: str) -> Optional[PRReview]:
        return (
            self._session.query(PRReview)
            .filter(
                PRReview.repo_full_name == repo_full_name,
                PRReview.head_sha == head_sha,
            )
            .first()
        )

    def create_pending(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        head_sha: str,
    ) -> PRReview:
        review = PRReview(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=head_sha,
            status="pending",
        )
        self.add(review)
        self.commit()
        return review

    def mark_in_progress(self, review: PRReview) -> PRReview:
        review.status = "in_progress"
        self.commit()
        return review

    def mark_completed(
        self,
        review: PRReview,
        total_findings: int,
        critical_count: int,
        high_count: int,
        latency_ms: int,
    ) -> PRReview:
        review.status = "completed"
        review.total_findings = total_findings
        review.critical_count = critical_count
        review.high_count = high_count
        review.latency_ms = latency_ms
        review.completed_at = datetime.utcnow()
        self.commit()
        return review

    def mark_failed(self, review: PRReview, error_message: str) -> PRReview:
        review.status = "failed"
        review.error_message = error_message[:1000]
        review.completed_at = datetime.utcnow()
        self.commit()
        return review
