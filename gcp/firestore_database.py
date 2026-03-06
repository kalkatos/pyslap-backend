from typing import Any, Optional
from google.cloud import firestore

from pyslap.interfaces.database import DatabaseInterface


class FirestoreDatabase(DatabaseInterface):
    """
    Google Cloud Firestore Implementation of the DatabaseInterface.
    Assumes ADC (Application Default Credentials) or explicit credentials
    are provided in the environment.
    """

    def __init__(self, project_id: Optional[str] = None):
        """
        Initializes the Firestore client. If project_id is None, it will be
        inferred from the environment.
        """
        self.db = firestore.Client(project=project_id)

    def create(self, collection: str, data: dict[str, Any]) -> str:
        """
        Creates a new document in the given collection.
        Returns the auto-generated document ID string.
        """
        coll_ref = self.db.collection(collection)
        _, doc_ref = coll_ref.add(data)
        return doc_ref.id

    def read(self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieves a document by its ID.
        Returns the dictionary of data or None if it doesn't exist.
        """
        doc_ref = self.db.collection(collection).document(record_id)
        doc = doc_ref.get()
        if doc.exists:  # type: ignore
            return doc.to_dict()  # type: ignore
        return None

    def update(self, collection: str, record_id: str, data: dict[str, Any]) -> bool:
        """
        Updates an existing document with the given fields.
        Returns True if successful. Uses merge=True to mimic typical update behavior.
        """
        doc_ref = self.db.collection(collection).document(record_id)
        # Check if exists first to return False if not found (matching Azure semantic)
        if not doc_ref.get().exists:  # type: ignore
            return False
            
        doc_ref.set(data, merge=True)
        return True

    def delete(self, collection: str, record_id: str) -> bool:
        """
        Deletes a document by ID. Firestore delete doesn't strictly fail if
        it didn't exist, but we check existence to return True/False truthfully.
        """
        doc_ref = self.db.collection(collection).document(record_id)
        if not doc_ref.get().exists:  # type: ignore
            return False
            
        doc_ref.delete()
        return True

    def query(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        A simple querying mechanism that maps a dict of equality filters
        to Firestore's where() clauses.
        """
        query_ref: Any = self.db.collection(collection)

        for property_name, value in filters.items():
            query_ref = query_ref.where(property_name, "==", value)

        results = []
        for doc in query_ref.stream():
            doc_dict = doc.to_dict()
            if doc_dict:
                 # It's useful to include the document ID in the result payload
                 # depending on application needs, but to be strictly agnostic
                 # we just return the data structure.
                results.append(doc_dict)

        return results
