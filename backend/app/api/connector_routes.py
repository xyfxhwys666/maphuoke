from typing import Literal

from backend.app.collection.service import CollectionService
from backend.app.connector.contracts import (
    ConnectorCreateTaskRequest,
    ConnectorHealth,
    ConnectorSearchRequest,
    ConnectorSearchResponse,
    ConnectorTaskList,
    ConnectorTaskResults,
    ConnectorTaskSummary,
)
from backend.app.connector.service import ConnectorFacade
from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix='/connector/v1', tags=['connector'])


def _service(request: Request) -> CollectionService:
    service = getattr(request.app.state, 'collection_service', None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='collection service is unavailable',
        )
    return service


def _account_scope(request: Request) -> str | None:
    value = request.headers.get('X-MapSearch-Account-Scope')
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(character.isspace() for character in value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='invalid MapSearch account scope',
        )
    return value


@router.get('/health', response_model=ConnectorHealth)
def health(request: Request) -> ConnectorHealth:
    return ConnectorFacade(getattr(request.app.state, 'collection_service', None)).health()


@router.get('/tasks', response_model=ConnectorTaskList)
def tasks(request: Request) -> ConnectorTaskList:
    return ConnectorTaskList(items=ConnectorFacade(_service(request)).list_tasks(
        account_scope=_account_scope(request),
    ))


@router.post('/tasks', response_model=ConnectorTaskSummary, status_code=status.HTTP_201_CREATED)
def create_task(payload: ConnectorCreateTaskRequest, request: Request) -> ConnectorTaskSummary:
    try:
        return ConnectorFacade(_service(request)).create_task(
            payload,
            account_scope=_account_scope(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get('/tasks/{task_id}', response_model=ConnectorTaskSummary)
def task(task_id: str, request: Request) -> ConnectorTaskSummary:
    try:
        return ConnectorFacade(_service(request)).get_task(
            task_id,
            account_scope=_account_scope(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get('/tasks/{task_id}/results', response_model=ConnectorTaskResults)
def task_results(task_id: str, request: Request) -> ConnectorTaskResults:
    try:
        return ConnectorFacade(_service(request)).get_results(
            task_id,
            account_scope=_account_scope(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post('/search', response_model=ConnectorSearchResponse)
def search(payload: ConnectorSearchRequest, request: Request) -> ConnectorSearchResponse:
    try:
        return ConnectorFacade(_service(request)).search(
            payload,
            account_scope=_account_scope(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post('/tasks/{task_id}/{action}', response_model=ConnectorTaskSummary)
def control_task(
    task_id: str,
    action: Literal['pause', 'resume', 'cancel'],
    request: Request,
) -> ConnectorTaskSummary:
    try:
        return ConnectorFacade(_service(request)).control_task(
            task_id,
            action,
            account_scope=_account_scope(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
