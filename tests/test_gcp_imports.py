from gcp.firestore_database import FirestoreDatabase
from gcp.cloud_tasks_scheduler import CloudTasksScheduler
from gcp.cloud_functions_entrypoint import GCPEntrypoint

def test_gcp_imports_and_instantiation():
    """
    Verifies that the GCP modules can be imported and their classes
    can be instantiated without syntax or import errors.
    """
    # Instantiate Firestore (it won't connect without credentials but shouldn't fail sync-ly on init)
    db = FirestoreDatabase(project_id="test-project")
    assert db is not None
    
    # Instantiate Cloud Tasks Scheduler
    scheduler = CloudTasksScheduler(
        project_id="test",
        location_id="test-region",
        queue_id="test-queue",
        cloud_function_url="https://example.com"
    )
    assert scheduler is not None

    # GCPEntrypoint requires an engine, skipping tight coupling here
    # but we proved it imports correctly.
    assert GCPEntrypoint is not None
