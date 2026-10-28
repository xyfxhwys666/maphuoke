from backend.app.collection.cities import tier3_plus_city_names
from backend.app.collection.models import CollectionTask
from backend.app.collection.service import CollectionService
from backend.app.providers.protocols import ProviderPaused
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator

router = APIRouter(prefix='/api/v1', tags=['collection'])
KNOWN_MODELS = {'doubao', 'deepseek'}


class NaturalLanguageCollectionRequest(BaseModel):
    request_text: str = Field(min_length=1, max_length=4000)
    keywords: list[str] = Field(default_factory=list, max_length=200)
    models: list[str] = Field(default_factory=list)
    continuous_mode: bool = True
    auto_deliver: bool = False
    verified_auto_deliver: bool = False

    @field_validator('models')
    @classmethod
    def clean_models(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip().lower() for value in values if value.strip()))
        return cleaned

    @field_validator('keywords')
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(len(value) > 100 for value in cleaned):
            raise ValueError('keyword is too long')
        return cleaned

    @model_validator(mode='after')
    def validate_delivery_modes(self) -> 'NaturalLanguageCollectionRequest':
        if self.auto_deliver and self.verified_auto_deliver:
            raise ValueError('automatic delivery modes are mutually exclusive')
        return self


class CollectionDeliveryRequest(BaseModel):
    target_url: str = Field(min_length=1, max_length=2000)
    bearer_token: str | None = Field(default=None, max_length=4000)


class CollectionExtensionRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=200)

    @field_validator('keywords')
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError('at least one keyword is required')
        if any(len(value) > 100 for value in cleaned):
            raise ValueError('keyword is too long')
        return cleaned


def _service(request: Request) -> CollectionService:
    service = getattr(request.app.state, 'collection_service', None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='collection service is unavailable',
        )
    return service


def _payload(task: CollectionTask) -> dict[str, object]:
    body = task.model_dump(mode='json')
    if task.status == 'queued' and any(
        unit.status == 'running' for unit in task.work_units
    ):
        body['status'] = 'running'
    cities = task.intent.cities or tier3_plus_city_names()
    body['plan'] = {
        'city_scope_label': task.intent.city_scope_label,
        'cities': cities,
        'city_count': len(cities),
        'keywords': task.intent.keywords,
        'models': task.intent.models,
        'provider_id': task.work_units[0].provider_id if task.work_units else None,
        'work_unit_count': len(task.work_units),
    }
    return body


def _load(service: CollectionService, task_id: str) -> CollectionTask:
    try:
        return service.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _model_keyword_suggestions(
    service: CollectionService,
    *,
    request_text: str,
    model_ids: list[str],
) -> list[str]:
    """Use connected judges opportunistically without blocking plan creation."""
    suggestions: list[str] = []
    for model_id in model_ids:
        judge = service.relevance_judges.get(model_id)
        parse_keywords = getattr(judge, 'parse_intent_keywords', None)
        if not callable(parse_keywords):
            continue
        browser = getattr(judge, 'browser', None)
        browser_state = getattr(browser, 'state', None)
        if browser is not None and str(getattr(browser_state, 'value', browser_state)).lower() != 'ready':
            continue
        try:
            parsed = parse_keywords(request_text)
        except (ProviderPaused, TimeoutError, ValueError, RuntimeError):
            continue
        if isinstance(parsed, list):
            suggestions.extend(str(item) for item in parsed)
    return list(dict.fromkeys(suggestions))


@router.get('/collection-models')
def collection_models() -> dict[str, list[dict[str, object]]]:
    return {'items': []}


@router.post('/collection-tasks/from-natural-language', status_code=status.HTTP_201_CREATED)
def create_collection_task(
    payload: NaturalLanguageCollectionRequest,
    request: Request,
) -> dict[str, object]:
    service = _service(request)
    unavailable = set(payload.models) - set(service.configured_models)
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'models are not configured: {sorted(unavailable)}',
        )
    if (payload.auto_deliver or payload.verified_auto_deliver) and not getattr(
        service.erp_adapter,
        'configured',
        False,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='ERP automatic delivery is not configured',
        )
    try:
        task = service.create_from_text(
            payload.request_text,
            explicit_keywords=payload.keywords or None,
            configured_models=set(payload.models),
            continuous_mode=payload.continuous_mode,
            auto_deliver=payload.auto_deliver,
            verified_auto_deliver=payload.verified_auto_deliver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _payload(task)


@router.get('/collection-tasks')
def list_collection_tasks(request: Request) -> dict[str, object]:
    service = _service(request)
    return {'items': [_payload(task) for task in service.list_tasks()]}


@router.post('/collection-browser/amap/open')
def open_amap_browser(request: Request) -> dict[str, object]:
    service = _service(request)
    provider = service.map_provider
    browser = getattr(provider, 'browser', None)
    if browser is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='dedicated Amap Chrome is unavailable',
        )
    url = str(getattr(provider, 'map_url', 'https://www.amap.com/'))
    try:
        open_url = getattr(browser, 'open_url', None)
        if callable(open_url):
            open_url(url)
        else:
            browser.start()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f'could not open dedicated Amap Chrome: {exc}',
        ) from exc
    browser_state = getattr(browser, 'state', 'ready')
    return {'url': url, 'state': getattr(browser_state, 'value', browser_state)}


@router.get('/collection-tasks/{task_id}/work-units')
def collection_work_units(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    task = _load(service, task_id)
    return {'items': [unit.model_dump(mode='json') for unit in task.work_units]}


@router.get('/collection-tasks/{task_id}')
def get_collection_task(task_id: str, request: Request) -> dict[str, object]:
    return _payload(_load(_service(request), task_id))


@router.post('/collection-tasks/{task_id}/start')
def start_collection_task(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    return _payload(service.start_async(task_id))


@router.post('/collection-tasks/{task_id}/pause')
def pause_collection_task(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    return _payload(service.pause(task_id))


@router.post('/collection-tasks/{task_id}/resume')
def resume_collection_task(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    return _payload(service.resume_async(task_id))


@router.post('/collection-tasks/{task_id}/cancel')
def cancel_collection_task(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    return _payload(service.cancel(task_id))


@router.post('/collection-tasks/{task_id}/retry-errors')
def retry_collection_errors(task_id: str, request: Request) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    return _payload(service.retry_errors_async(task_id))


@router.post('/collection-tasks/{task_id}/extend')
def extend_collection_task(
    task_id: str,
    payload: CollectionExtensionRequest,
    request: Request,
) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    service.extend_keywords(task_id, payload.keywords)
    return _payload(service.start_async(task_id))


@router.post('/collection-tasks/{task_id}/deliver')
def deliver_collection_results(
    task_id: str,
    payload: CollectionDeliveryRequest,
    request: Request,
) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    try:
        deliveries = service.deliver_results(
            task_id,
            target_url=payload.target_url,
            bearer_token=payload.bearer_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return {
        'sent': sum(result.status in {'delivered', 'duplicate'} for _lead, result in deliveries),
        'failed': sum(result.status == 'failed' for _lead, result in deliveries),
        'items': [
            {'lead': lead.model_dump(mode='json'), 'delivery': result.model_dump(mode='json')}
            for lead, result in deliveries
        ],
    }


@router.post('/collection-tasks/{task_id}/refresh-amap-contacts-and-deliver')
def refresh_amap_contacts_and_deliver(
    task_id: str,
    payload: CollectionDeliveryRequest,
    request: Request,
) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    try:
        return _payload(service.refresh_amap_contacts_and_deliver_async(
            task_id,
            target_url=payload.target_url,
            bearer_token=payload.bearer_token,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post('/collection-tasks/{task_id}/leads/{lead_id}/deliver')
def deliver_collection_lead(
    task_id: str,
    lead_id: str,
    payload: CollectionDeliveryRequest,
    request: Request,
) -> dict[str, object]:
    service = _service(request)
    _load(service, task_id)
    try:
        deliveries = service.deliver_results(
            task_id,
            target_url=payload.target_url,
            bearer_token=payload.bearer_token,
            lead_id=lead_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    lead, result = deliveries[0]
    return {'lead': lead.model_dump(mode='json'), 'delivery': result.model_dump(mode='json')}
