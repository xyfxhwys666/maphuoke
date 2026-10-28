from backend.app.api.collection_routes import router as collection_router
from backend.app.api.connector_routes import router as connector_router
from backend.app.api.routes import router
from backend.app.collection.service import CollectionService
from backend.app.config import load_settings
from backend.app.db import Base, create_database
from backend.app.runtime import build_runtime_components
from backend.app.services.batch_jobs import BatchJobManager
from backend.app.services.search_task import CompanySearchService
from backend.app.storage import models as _storage_models  # noqa: F401 - register tables with Base
from backend.app.storage.repositories import CollectionRepository, TaskRepository
from fastapi import FastAPI


def create_app(
    *,
    database_url: str | None = None,
    service: CompanySearchService | None = None,
    collection_service: CollectionService | None = None,
    batch_manager: BatchJobManager | None = None,
) -> FastAPI:
    app = FastAPI(title='Map Lead Platform', version='0.1.0')
    settings = load_settings()
    repository = None
    collection_repository = None

    if service is None:
        engine, session_factory = create_database(
            database_url or settings.database_url
        )
        Base.metadata.create_all(engine)
        repository = TaskRepository(session_factory)
        collection_repository = CollectionRepository(session_factory)
        runtime = build_runtime_components(
            settings,
            repository=repository,
            collection_repository=collection_repository,
        )
        service = runtime.service
        app.state.runtime_components = runtime
    else:
        app.state.runtime_components = None
    app.state.search_service = service
    app.state.collection_service = (
        collection_service
        if collection_service is not None
        else getattr(app.state.runtime_components, 'collection_service', None)
    )
    app.state.batch_manager = batch_manager or BatchJobManager(
        service,
        max_items=settings.batch_max_items,
        request_interval_seconds=settings.batch_request_interval_seconds,
        repository=repository,
    )

    def shutdown() -> None:
        app.state.batch_manager.close()
        if app.state.runtime_components is not None:
            app.state.runtime_components.close()

    app.router.add_event_handler('shutdown', shutdown)

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    app.include_router(router)
    app.include_router(collection_router)
    app.include_router(connector_router)
    return app


app = create_app()
