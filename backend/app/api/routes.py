from pathlib import Path
from typing import Any

from backend.app.batch.importers import CompanyInputImporter, ImportValidationError
from backend.app.domain.task_state import SearchTask
from backend.app.services.batch_jobs import BatchJobManager
from backend.app.services.search_task import CompanySearchService
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/v1')


class CreateTaskRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=256)
    city: str = Field(min_length=1, max_length=128)
    discovery_provider: str = 'amap_web'
    enrichment_provider: str = 'doubao_web'
    required_contacts: list[str] = Field(default_factory=lambda: ['mobile', 'email', 'wechat'])
    auto_deliver: bool = False
    allow_map_only_verification: bool = False


class CandidateActionRequest(BaseModel):
    candidate_id: str | None = None


def get_service(request: Request) -> CompanySearchService:
    return request.app.state.search_service


def get_batch_manager(request: Request) -> BatchJobManager:
    return request.app.state.batch_manager


def task_payload(task: SearchTask) -> dict[str, Any]:
    return task.model_dump(mode='json')


def get_task_or_404(service: CompanySearchService, task_id: str) -> SearchTask:
    try:
        return service.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def batch_payload(manager: BatchJobManager, batch_id: str) -> dict[str, Any]:
    try:
        return manager.get_job(batch_id).model_dump(mode='json')
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('/providers')
def providers(service: CompanySearchService = Depends(get_service)) -> dict[str, list[dict[str, object]]]:
    return {
        'map_discovery': [
            {
                'id': provider.id,
                'label': provider.label,
                'configured': provider.configured,
            }
            for provider in service.map_providers.values()
        ],
        'enrichment': [
            {
                'id': gateway.id,
                'label': '豆包网页' if gateway.id == 'doubao_web' else 'Fake Doubao',
                'configured': getattr(gateway, 'configured', True),
            }
            for gateway in service.doubao_gateways.values()
        ],
    }


@router.get('/browser-status')
def browser_status(service: CompanySearchService = Depends(get_service)) -> dict[str, object]:
    provider = service.map_providers.get('amap_web', service.map_provider)
    browser = getattr(provider, 'browser', None)
    state = getattr(browser, 'state', 'stopped')
    return {'state': getattr(state, 'value', state), 'provider': provider.id}


@router.post('/company-search-tasks', status_code=status.HTTP_201_CREATED)
def create_task(
    request: CreateTaskRequest,
    service: CompanySearchService = Depends(get_service),
) -> dict[str, Any]:
    task = service.create_task(
        company_name=request.company_name,
        city=request.city,
        required_contacts=request.required_contacts,
        auto_deliver=request.auto_deliver,
        allow_map_only_verification=request.allow_map_only_verification,
        discovery_provider=request.discovery_provider,
        enrichment_provider=request.enrichment_provider,
    )
    return task_payload(task)


@router.post('/company-search-tasks/{task_id}/start')
def start_task(task_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    get_task_or_404(service, task_id)
    return task_payload(service.start(task_id))


@router.get('/company-search-tasks/{task_id}')
def get_task(task_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    return task_payload(get_task_or_404(service, task_id))


@router.post('/company-search-tasks/{task_id}/pause')
def pause_task(task_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    get_task_or_404(service, task_id)
    return task_payload(service.pause(task_id))


@router.post('/company-search-tasks/{task_id}/resume')
def resume_task(task_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    get_task_or_404(service, task_id)
    return task_payload(service.resume(task_id))


@router.post('/company-search-tasks/{task_id}/enrich')
def enrich_task(
    task_id: str,
    request: CandidateActionRequest,
    service: CompanySearchService = Depends(get_service),
) -> dict[str, Any]:
    if not request.candidate_id:
        raise HTTPException(status_code=422, detail='candidate_id is required')
    get_task_or_404(service, task_id)
    return task_payload(service.enrich(task_id, candidate_id=request.candidate_id))


@router.post('/company-search-tasks/{task_id}/verify')
def verify_task(
    task_id: str,
    request: CandidateActionRequest,
    service: CompanySearchService = Depends(get_service),
) -> dict[str, Any]:
    get_task_or_404(service, task_id)
    return task_payload(service.verify(task_id, candidate_id=request.candidate_id))


@router.post('/company-search-tasks/{task_id}/deliver')
def deliver_task(
    task_id: str,
    request: CandidateActionRequest,
    service: CompanySearchService = Depends(get_service),
) -> dict[str, Any]:
    if not request.candidate_id:
        raise HTTPException(status_code=422, detail='candidate_id is required')
    get_task_or_404(service, task_id)
    result = service.deliver(task_id, candidate_id=request.candidate_id)
    return {'task': task_payload(service.get_task(task_id)), 'delivery': result.model_dump(mode='json')}


@router.post('/company-search-tasks/{task_id}/retry-errors')
def retry_errors(task_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    get_task_or_404(service, task_id)
    return task_payload(service.retry_errors(task_id))


@router.post('/leads/{lead_id}/deliver')
def deliver_lead(lead_id: str, service: CompanySearchService = Depends(get_service)) -> dict[str, Any]:
    try:
        result = service.deliver_lead(lead_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {'delivery': result.model_dump(mode='json')}


@router.get('/erp-config')
def erp_config(service: CompanySearchService = Depends(get_service)) -> dict[str, object]:
    return {
        'configured': bool(getattr(service.erp_adapter, 'configured', False)),
        'auto_deliver_default': False,
    }


@router.post('/batches', status_code=status.HTTP_201_CREATED)
async def create_batch(
    request: Request,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    filename = request.query_params.get('filename') or request.headers.get('x-filename') or 'companies.csv'
    body = await request.body()
    try:
        if Path(filename).suffix.casefold() == '.xlsx':
            items = CompanyInputImporter.from_xlsx(body)
        else:
            items = CompanyInputImporter.from_csv(body)
        job = manager.create_job(filename=filename, items=items)
    except (ImportValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job.model_dump(mode='json')


@router.post('/batches/{batch_id}/start')
def start_batch(
    batch_id: str,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    try:
        return manager.start(batch_id).model_dump(mode='json')
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get('/batches/{batch_id}')
def get_batch(
    batch_id: str,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    return batch_payload(manager, batch_id)


@router.post('/batches/{batch_id}/retry-errors')
def retry_batch_errors(
    batch_id: str,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    try:
        return manager.retry_errors(batch_id).model_dump(mode='json')
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/batches/{batch_id}/pause')
def pause_batch(
    batch_id: str,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    try:
        return manager.pause(batch_id).model_dump(mode='json')
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/batches/{batch_id}/resume')
def resume_batch(
    batch_id: str,
    manager: BatchJobManager = Depends(get_batch_manager),
) -> dict[str, Any]:
    try:
        return manager.resume(batch_id).model_dump(mode='json')
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
