export type TaskStatus =
  | 'created'
  | 'discovering_map'
  | 'candidates_ready'
  | 'enriching_doubao'
  | 'verifying'
  | 'ready'
  | 'delivering'
  | 'completed'
  | 'paused'
  | 'waiting_for_login'
  | 'waiting_for_challenge'
  | 'completed_with_errors';

export interface MapPoiCandidate {
  candidate_id: string;
  company_name: string;
  city: string;
  address: string | null;
  telephone: string | null;
  mobile: string | null;
  category: string | null;
  longitude: number | null;
  latitude: number | null;
  poi_id: string | null;
  source_url: string | null;
  source_urls: string[];
  discovery_channel: string;
  raw_text: string | null;
  source_metadata: Record<string, unknown>;
  captured_at: string;
  evidence_snapshot_id: string | null;
}

export interface EvidenceValue {
  value: string | null;
  status: 'captured' | 'source_backed' | 'verified';
  source_urls: string[];
  quotes: string[];
}

export interface LeadRecord {
  id: string;
  task_id: string;
  city: string;
  company_name: string;
  mobile: string | null;
  telephone: string | null;
  contact_person_name: string | null;
  contact_person_role: string | null;
  email: string | null;
  wechat: string | null;
  address: string | null;
  service_intro: string | null;
  discovery_channel: string;
  enrichment_model: string | null;
  source_url: string | null;
  source_urls: string[];
  evidence_quotes: string[];
  source_metadata: Record<string, unknown>;
  field_evidence: Record<string, EvidenceValue>;
  company_name_verification_status: string;
  contact_verification_status: string;
  contact_evidence_urls: string[];
  contact_evidence_quotes: string[];
  contact_evidence_grade: string | null;
  contact_evidence_score: number | null;
  enrichment_state: string;
  delivery_status: string;
  delivery_fingerprint: string | null;
  delivery_at: string | null;
}

export interface CompanyProgress {
  candidate_id: string;
  discovery_state: string;
  enrichment_state: string;
  verification_state: string;
  delivery_status: string;
  retry_count: number;
  retry_after: string | null;
  last_updated_at: string | null;
  last_error: string | null;
}

export interface TaskCheckpoint {
  current_stage: string;
  current_company_index: number;
  current_company_id: string | null;
  completed_company_ids: string[];
  browser_state: string;
  last_successful_query_at: string | null;
  retry_after: string | null;
  failed_company_ids: string[];
  delivery_fingerprints: string[];
  operation_ids: string[];
}

export interface SearchTask {
  id: string;
  company_name: string;
  city: string;
  discovery_provider: string;
  enrichment_provider: string;
  required_contacts: string[];
  auto_deliver: boolean;
  allow_map_only_verification: boolean;
  status: TaskStatus;
  candidates: MapPoiCandidate[];
  leads: LeadRecord[];
  progress: Record<string, CompanyProgress>;
  checkpoint: TaskCheckpoint;
  errors: string[];
}

export type CollectionTaskStatus =
  | 'planned'
  | 'queued'
  | 'running'
  | 'paused'
  | 'needs_attention'
  | 'completed'
  | 'completed_with_errors'
  | 'cancelled';

export type CollectionWorkUnitStatus =
  | 'planned'
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'no_result'
  | 'skipped_limit'
  | 'retry_wait'
  | 'needs_attention'
  | 'failed'
  | 'paused';

export interface CollectionIntent {
  request_text: string;
  cities: string[];
  all_cities: boolean;
  city_scope_label: string;
  keywords: string[];
  models: string[];
  required_contacts: string[];
  contact_match: 'any' | 'all';
  limit_per_city: number | null;
  target_valid_contacts: number | null;
}

export interface CollectionWorkUnit {
  id: string;
  city: string;
  keyword: string;
  provider_id: string;
  models: string[];
  required_contacts: string[];
  contact_match: 'any' | 'all';
  limit_per_city: number | null;
  status: CollectionWorkUnitStatus;
  candidate_count: number;
  company_name_candidate_count: number;
  map_match_count: number;
  relevant_count: number;
  contact_count: number;
  retry_count: number;
  retry_after: string | null;
  last_error: string | null;
  updated_at: string;
}

export interface CollectionRelevanceDecision {
  candidate_id: string;
  model_id: string;
  keyword: string | null;
  status: 'relevant' | 'not_relevant' | 'review';
  reason: string;
  confidence: number | null;
  created_at: string;
}

export interface CollectionSummary {
  total_work_units: number;
  completed_work_units: number;
  candidate_count: number;
  relevant_count: number;
  review_count: number;
  contact_count: number;
  verified_count: number;
  erp_success_count: number;
  erp_failure_count: number;
  target_valid_contacts: number | null;
  valid_contact_count: number;
  no_phone_count: number;
  rejected_count: number;
  source_exhausted: boolean;
}

export interface CollectionCheckpoint {
  current_stage: string;
  current_work_unit_id: string | null;
  completed_work_unit_ids: string[];
  failed_work_unit_ids: string[];
  browser_state: string;
  retry_after: string | null;
}

export interface CollectionPlan {
  city_scope_label: string;
  cities: string[];
  city_count: number;
  keywords: string[];
  models: string[];
  provider_id: string | null;
  work_unit_count: number;
}

export type CollectionResult = LeadRecord;

export interface CollectionTask {
  id: string;
  name: string;
  request_text: string;
  created_at: string;
  intent: CollectionIntent;
  status: CollectionTaskStatus;
  continuous_mode: boolean;
  auto_deliver: boolean;
  verified_auto_deliver: boolean;
  completion_reason: 'target_reached' | 'source_exhausted' | 'completed_with_errors' | null;
  plan: CollectionPlan;
  work_units: CollectionWorkUnit[];
  company_name_candidates: Array<{
    company_name: string;
    city: string;
    matched_keyword: string;
    source_urls: string[];
    evidence_quotes: string[];
    discovery_channel: 'public_web' | 'amap_keyword';
    discovered_at: string;
  }>;
  candidates: MapPoiCandidate[];
  results: CollectionResult[];
  relevance_decisions: Record<string, CollectionRelevanceDecision[]>;
  summary: CollectionSummary;
  checkpoint: CollectionCheckpoint;
  errors: string[];
}

export interface CollectionModelOption {
  id: string;
  label: string;
  configured: boolean;
}

export type BatchJobStatus = 'created' | 'running' | 'paused' | 'completed' | 'completed_with_errors';
export type BatchItemStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface BatchItem {
  item_id: string;
  company_name: string;
  city: string;
  row_number: number;
  status: BatchItemStatus;
  task_id: string | null;
  candidate_count: number;
  error: string | null;
  retry_count: number;
  updated_at: string;
}

export interface BatchJob {
  id: string;
  filename: string;
  status: BatchJobStatus;
  total: number;
  items: BatchItem[];
  created_at: string;
  updated_at: string;
}

export interface DeliveryResult {
  status: 'delivered' | 'display_only' | 'failed' | 'duplicate';
  reasons: string[];
  operation_id: string | null;
  error: string | null;
  payload: Record<string, unknown> | null;
}

export interface DeliveryResponse {
  task: SearchTask;
  delivery: DeliveryResult;
}

export interface CollectionDeliveryResponse {
  sent: number;
  failed: number;
  items: Array<{ lead: LeadRecord; delivery: DeliveryResult }>;
}
