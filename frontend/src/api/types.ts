/**
 * Response shapes mirrored from the backend routes.
 *
 * Kept terse — only the fields the SPA actually renders. Drift
 * between frontend and backend is caught at build-time by mypy
 * on the backend and tsc on the frontend; the SPA is thin enough
 * that a divergence would fail immediately in the upload / workflow
 * flows.
 */

export interface SignupResponse {
  tenant_id: string;
  firm_id: string;
  firm_administrator_id: string;
  passkey_enrollment_required: boolean;
}

export interface SessionTokenResponse {
  token: string;
  expires_at: string;
  user_id: string;
  tenant_id: string;
}

export interface MeResponse {
  user_id: string;
  tenant_id: string;
  firm_id: string | null;
  email: string;
  role: string;
  session_expires_at: string;
}

export interface DocumentResponse {
  document_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  sha256_hex: string;
  ingest_state: string;
  scan_state: string;
  uploaded_at: string;
}

export interface DocumentListResponse {
  engagement_id: string;
  documents: DocumentResponse[];
}

export interface UploadResponse {
  document_id: string;
  sha256_hex: string;
  byte_size: number;
  content_type: string;
}

export interface WorkflowRun {
  run_id: string;
  template_id: string;
  engagement_id: string;
  state: string;
  current_step_index: number;
  pause_reason: { required_role?: string; reason?: string; step_name?: string };
  context: Record<string, unknown>;
  error: string | null;
}

export interface WorkflowRunList {
  engagement_id: string;
  runs: WorkflowRun[];
}

export interface WorkflowStepRun {
  id: string;
  step_index: number;
  step_name: string;
  step_type: string;
  state: string;
  started_at: string;
  ended_at: string | null;
  attempt: number;
  payload: Record<string, unknown>;
  error: string | null;
}

export interface WorkflowStepList {
  run_id: string;
  steps: WorkflowStepRun[];
}
