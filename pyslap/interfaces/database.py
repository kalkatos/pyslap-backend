from abc import ABC, abstractmethod
from typing import Any, Optional


class DatabaseInterface(ABC):
    """
    Interface defining strict CRUD (Create, Read, Update, Delete) operations
    for the PySlap backend framework. This interface solely handles data
    persistence and retrieval, agnostic to underlying DB technology.
    """

    @abstractmethod
    def create(self, collection: str, data: dict[str, Any]) -> str:
        """
        Creates a new record in the specified collection.
        Returns the unique identifier of the created record.
        """
        pass

    @abstractmethod
    def read(self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieves a record by its identifier from the specified collection.
        Returns the record data or None if not found.
        """
        pass

    @abstractmethod
    def update(self, collection: str, record_id: str, data: dict[str, Any],
               expected_version: Optional[int] = None) -> bool:
        """
        Updates an existing record with new data.
        If expected_version is provided, the update only succeeds when the
        record's current 'version' field matches. Returns False on mismatch
        (CAS failure) or if the record doesn't exist.
        """
        pass

    @abstractmethod
    def delete(self, collection: str, record_id: str) -> bool:
        """
        Deletes a record from the specified collection.
        Returns True if successful, False otherwise.
        """
        pass

    @abstractmethod
    def query(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Retrieves records from a collection that match the provided filters.

        Supports comparison operators via suffixed keys:
          - "field__lt": value  →  field < value
          - "field__lte": value →  field <= value
          - "field__gt": value  →  field > value
          - "field__gte": value →  field >= value
          - "field__ne": value  →  field != value
          - "field": value      →  field = value (exact match)
        """
        pass

    @abstractmethod
    def delete_by_filter (self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Deletes all records matching the provided filters and returns the
        deleted records.

        Supports comparison operators via suffixed keys:
          - "field__lt": value  →  field < value
          - "field__lte": value →  field <= value
          - "field__gt": value  →  field > value
          - "field__gte": value →  field >= value
          - "field__ne": value  →  field != value
          - "field": value      →  field = value (exact match)
        """
        pass
