from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class DatabaseInterface(ABC):
    """
    Interface defining strict CRUD (Create, Read, Update, Delete) operations
    for the PySlap backend framework. This interface solely handles data
    persistence and retrieval, agnostic to underlying DB technology.
    """

    @abstractmethod
    def create(self, collection: str, data: Dict[str, Any]) -> str:
        """
        Creates a new record in the specified collection.
        Returns the unique identifier of the created record.
        """
        pass

    @abstractmethod
    def read(self, collection: str, record_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a record by its identifier from the specified collection.
        Returns the record data or None if not found.
        """
        pass

    @abstractmethod
    def update(self, collection: str, record_id: str, data: Dict[str, Any]) -> bool:
        """
        Updates an existing record with new data.
        Returns True if the update was successful, False otherwise.
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
    def query(self, collection: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Retrieves records from a collection that match the provided filters.
        """
        pass
