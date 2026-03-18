from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Optional


class DatabaseInterface(ABC):
    """
    Interface defining strict CRUD (Create, Read, Update, Delete) operations
    for the PySlap backend framework. This interface solely handles data
    persistence and retrieval, agnostic to underlying DB technology.
    """

    @abstractmethod
    def create(self, collection: str, data: dict[str, Any], fail_if_exists: bool = False) -> Optional[str]:
        """
        Creates a new record in the specified collection.
        Returns the unique identifier of the created record, or None if
        fail_if_exists=True and a record with the same 'id' already exists.
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
    def conditional_update (self, collection: str, record_id: str, data: dict[str, Any],
                           filters: dict[str, Any]) -> bool:
        """
        Updates an existing record with new data ONLY if it matches the
        provided filters. Returns True if the update was successful,
        False otherwise (including record not found).
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
          - "field__in": list   →  field IN (values)
          - "field": value      →  field = value (exact match)
        """
        pass

    @abstractmethod
    def start_transaction (self) -> None:
        """
        Starts a new database transaction.
        Subsequent create/read/update/delete operations should be atomic
        until commit() or rollback() is called.
        """
        pass

    @abstractmethod
    def commit (self) -> None:
        """
        Finalizes the current transaction, persisting all changes made.
        """
        pass

    @abstractmethod
    def rollback (self) -> None:
        """
        Reverts all changes made during the current transaction.
        """
        pass

    @contextmanager
    def transaction (self):
        """
        Context manager that wraps a block in a transaction.
        Commits on success, rolls back (and re-raises) on any exception.
        Guarantees the lock is always released regardless of what happens inside the block.
        """
        self.start_transaction()
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise

    @abstractmethod
    def delete_by_filter (self, collection: str, filters: dict[str, Any],
                          return_ids_only: bool = False) -> list[dict[str, Any]]:
        """
        Deletes all records matching the provided filters and returns the
        deleted records.

        When `return_ids_only=True`, returns lightweight `[{"id": rid}]` dicts
        instead of full records, avoiding loading large JSON blobs into memory.

        Supports comparison operators via suffixed keys:
          - "field__lt": value  →  field < value
          - "field__lte": value →  field <= value
          - "field__gt": value  →  field > value
          - "field__gte": value →  field >= value
          - "field__ne": value  →  field != value
          - "field__in": list   →  field IN (values)
          - "field": value      →  field = value (exact match)
        """
        pass
