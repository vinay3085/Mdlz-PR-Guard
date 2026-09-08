from typing import Generic, List, Optional, Type, TypeVar
from sqlalchemy.orm import Session
from app.models.database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    Generic repository providing common CRUD operations.
    All domain repositories extend this class (Liskov Substitution Principle).
    """

    def __init__(self, session: Session, model: Type[T]) -> None:
        self._session = session
        self._model = model

    def get_by_id(self, entity_id: int) -> Optional[T]:
        return self._session.get(self._model, entity_id)

    def list_all(self) -> List[T]:
        return self._session.query(self._model).all()

    def add(self, entity: T) -> T:
        self._session.add(entity)
        self._session.flush()
        return entity

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def close(self) -> None:
        self._session.close()
