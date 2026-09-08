from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from app.models.database import Installation
from app.repositories.base import BaseRepository


class InstallationRepository(BaseRepository[Installation]):
    def __init__(self, session: Session) -> None:
        super().__init__(session, Installation)

    def get_by_installation_id(self, installation_id: int) -> Optional[Installation]:
        return (
            self._session.query(Installation)
            .filter(Installation.installation_id == installation_id)
            .first()
        )

    def upsert(
        self,
        installation_id: int,
        org: str,
        account_login: str,
        status: str = "active",
    ) -> Installation:
        existing = self.get_by_installation_id(installation_id)
        if existing:
            existing.status = status
            existing.org = org
            existing.account_login = account_login
            existing.updated_at = datetime.utcnow()
            self.commit()
            return existing

        installation = Installation(
            installation_id=installation_id,
            org=org,
            account_login=account_login,
            status=status,
        )
        self.add(installation)
        self.commit()
        return installation
