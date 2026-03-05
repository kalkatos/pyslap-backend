import os
import json
import uuid
from typing import Any, Optional

from azure.data.tables import TableServiceClient, UpdateMode
from azure.core.exceptions import ResourceNotFoundError

from pyslap.interfaces.database import DatabaseInterface


class AzureTableDatabase(DatabaseInterface):
    """
    Azure Table Storage implementation of DatabaseInterface.
    Each collection maps to a distinct Azure Table.
    PartitionKey is always 'default'.
    RowKey is the record_id.
    """
    
    def __init__(self, connection_string: Optional[str] = None):
        if not connection_string:
            connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            if not connection_string:
                raise ValueError("AZURE_STORAGE_CONNECTION_STRING is required in environment variables.")
                
        self.service_client = TableServiceClient.from_connection_string(connection_string)

    def _get_table_client(self, collection: str):
        # Table names must be alphanumeric and between 3 and 63 characters
        table_name = "".join(c for c in collection if c.isalnum())
        if len(table_name) < 3:
            table_name = table_name.ljust(3, "0")
            
        table_client = self.service_client.get_table_client(table_name)
        try:
            table_client.create_table()
        except Exception:
            # Table already exists or another error (like auth)
            pass
        return table_client

    def _serialize_entity(self, data: dict[str, Any]) -> dict[str, Any]:
        entity = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                entity[k] = json.dumps(v)
            else:
                entity[k] = v
        return entity

    def _deserialize_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        data = {}
        for k, v in entity.items():
            if k in ("PartitionKey", "RowKey", "Timestamp", "etag"):
                continue
            
            if isinstance(v, str) and len(v) > 0 and (v.startswith('{') or v.startswith('[')):
                try:
                    data[k] = json.loads(v)
                except json.JSONDecodeError:
                    data[k] = v
            else:
                data[k] = v
        return data

    def create(self, collection: str, data: dict[str, Any]) -> str:
        record_id = data.get("id", str(uuid.uuid4()))
        if "id" not in data:
            data["id"] = record_id
            
        client = self._get_table_client(collection)
        
        entity = self._serialize_entity(data)
        entity["PartitionKey"] = "default"
        entity["RowKey"] = record_id
        
        client.create_entity(entity=entity)
        return record_id

    def read(self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        client = self._get_table_client(collection)
        try:
            entity = client.get_entity(partition_key="default", row_key=record_id)
            return self._deserialize_entity(entity)
        except ResourceNotFoundError:
            return None

    def update(self, collection: str, record_id: str, data: dict[str, Any]) -> bool:
        client = self._get_table_client(collection)
        entity = self._serialize_entity(data)
        entity["PartitionKey"] = "default"
        entity["RowKey"] = record_id
        
        try:
            # mode="merge" updates existing properties and adds new ones.
            client.update_entity(mode=UpdateMode.MERGE, entity=entity)
            return True
        except ResourceNotFoundError:
            return False

    def delete(self, collection: str, record_id: str) -> bool:
        client = self._get_table_client(collection)
        try:
            client.delete_entity(partition_key="default", row_key=record_id)
            return True
        except ResourceNotFoundError:
            return False

    def query(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        client = self._get_table_client(collection)
        
        # Build query string
        query_parts = []
        for k, v in filters.items():
            if isinstance(v, str):
                v_clean = v.replace("'", "''")
                query_parts.append(f"{k} eq '{v_clean}'")
            elif isinstance(v, bool):
                query_parts.append(f"{k} eq {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                query_parts.append(f"{k} eq {v}")
            elif isinstance(v, (dict, list)):
                json_v = json.dumps(v).replace("'", "''")
                query_parts.append(f"{k} eq '{json_v}'")
                
        query_str = " and ".join(query_parts) if query_parts else None
        
        try:
            if query_str:
                entities = client.query_entities(query_filter=query_str)
            else:
                entities = client.list_entities()
                
            return [self._deserialize_entity(e) for e in entities]
            
        except ResourceNotFoundError:
            # Table might not exist yet if queried before any insertion
            return []
