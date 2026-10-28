import type {
  BatchJob,
  CollectionTask,
  CollectionDeliveryResponse,
  DeliveryResponse,
  DeliveryResult,
  LeadRecord,
  SearchTask,
} from './types';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export interface CreateTaskInput {
  company_name: string;
  city: string;
  required_contacts: string[];
  auto_deliver: boolean;
}

export function createTask(input: CreateTaskInput): Promise<SearchTask> {
  return request<SearchTask>('/api/v1/company-search-tasks', {
    method: 'POST',
    body: JSON.stringify({
      ...input,
      discovery_provider: 'amap_web',
      enrichment_provider: 'doubao_web',
      allow_map_only_verification: false,
    }),
  });
}

export function startTask(taskId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/start`, { method: 'POST' });
}

export function getTask(taskId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}`);
}

export function pauseTask(taskId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/pause`, { method: 'POST' });
}

export function resumeTask(taskId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/resume`, { method: 'POST' });
}

export function enrichTask(taskId: string, candidateId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/enrich`, {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId }),
  });
}

export function verifyTask(taskId: string, candidateId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/verify`, {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId }),
  });
}

export function deliverTask(taskId: string, candidateId: string): Promise<DeliveryResponse> {
  return request<DeliveryResponse>(`/api/v1/company-search-tasks/${taskId}/deliver`, {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId }),
  });
}

export function createBatch(file: File): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches?filename=${encodeURIComponent(file.name)}`, {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  });
}

export function startBatch(batchId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches/${batchId}/start`, { method: 'POST' });
}

export function getBatch(batchId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches/${batchId}`);
}

export function retryBatchErrors(batchId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches/${batchId}/retry-errors`, { method: 'POST' });
}

export function pauseBatch(batchId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches/${batchId}/pause`, { method: 'POST' });
}

export function resumeBatch(batchId: string): Promise<BatchJob> {
  return request<BatchJob>(`/api/v1/batches/${batchId}/resume`, { method: 'POST' });
}

export function retryTaskErrors(taskId: string): Promise<SearchTask> {
  return request<SearchTask>(`/api/v1/company-search-tasks/${taskId}/retry-errors`, { method: 'POST' });
}

export interface CreateCollectionTaskInput {
  request_text: string;
  models?: string[];
  continuous_mode: boolean;
  auto_deliver: boolean;
  verified_auto_deliver: boolean;
}

export function createCollectionTask(input: CreateCollectionTaskInput): Promise<CollectionTask> {
  return request<CollectionTask>('/api/v1/collection-tasks/from-natural-language', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function listCollectionTasks(): Promise<{ items: CollectionTask[] }> {
  return request<{ items: CollectionTask[] }>('/api/v1/collection-tasks');
}

export function openAmapBrowser(): Promise<{ url: string; state: string }> {
  return request<{ url: string; state: string }>('/api/v1/collection-browser/amap/open', { method: 'POST' });
}

export function startCollectionTask(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}/start`, { method: 'POST' });
}

export function getCollectionTask(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}`);
}

export function pauseCollectionTask(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}/pause`, { method: 'POST' });
}

export function resumeCollectionTask(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}/resume`, { method: 'POST' });
}

export function cancelCollectionTask(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}/cancel`, { method: 'POST' });
}

export function retryCollectionTaskErrors(taskId: string): Promise<CollectionTask> {
  return request<CollectionTask>(`/api/v1/collection-tasks/${taskId}/retry-errors`, { method: 'POST' });
}

export function deliverCollectionResults(
  taskId: string,
  targetUrl: string,
  bearerToken: string,
): Promise<CollectionDeliveryResponse> {
  return request<CollectionDeliveryResponse>(`/api/v1/collection-tasks/${taskId}/deliver`, {
    method: 'POST',
    body: JSON.stringify({ target_url: targetUrl, bearer_token: bearerToken || null }),
  });
}

export function deliverCollectionLead(
  taskId: string,
  leadId: string,
  targetUrl: string,
  bearerToken: string,
): Promise<{ lead: LeadRecord; delivery: DeliveryResult }> {
  return request<{ lead: LeadRecord; delivery: DeliveryResult }>(
    `/api/v1/collection-tasks/${taskId}/leads/${leadId}/deliver`,
    {
      method: 'POST',
      body: JSON.stringify({ target_url: targetUrl, bearer_token: bearerToken || null }),
    },
  );
}
