/**
 * Typed wrappers around each backend route the SPA calls.
 *
 * Route URLs in one place — prevents typos drifting from the
 * backend's path declarations. When a backend route changes
 * signature, TypeScript surface changes here, and every caller
 * breaks until fixed.
 */

import { apiFetch } from "./client";
import type {
  DocumentListResponse,
  DocumentResponse,
  MeResponse,
  SignupResponse,
  UploadResponse,
  WorkflowRun,
  WorkflowRunList,
  WorkflowStepList,
} from "./types";

// ---- Auth ----------------------------------------------------------

export function signup(body: {
  firm_name: string;
  principal_email: string;
  principal_display_name: string;
}): Promise<SignupResponse> {
  return apiFetch<SignupResponse>("/auth/signup", {
    method: "POST",
    body,
    auth: false,
  });
}

export function getCurrentUser(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/auth/me");
}

export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}

// ---- Documents -----------------------------------------------------

export function listDocuments(
  engagementId: string,
): Promise<DocumentListResponse> {
  return apiFetch<DocumentListResponse>(
    `/engagements/${engagementId}/documents`,
  );
}

export function getDocument(documentId: string): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`/documents/${documentId}`);
}

export function uploadDocument(
  engagementId: string,
  file: File,
): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  return apiFetch<UploadResponse>(
    `/engagements/${engagementId}/documents`,
    { method: "POST", formData: fd },
  );
}

// ---- Workflows -----------------------------------------------------

export function startWorkflow(
  engagementId: string,
  templateId: string,
): Promise<WorkflowRun> {
  return apiFetch<WorkflowRun>(
    `/engagements/${engagementId}/workflows`,
    { method: "POST", body: { template_id: templateId } },
  );
}

export function getWorkflow(runId: string): Promise<WorkflowRun> {
  return apiFetch<WorkflowRun>(`/workflows/${runId}`);
}

export function listWorkflowRuns(
  engagementId: string,
): Promise<WorkflowRunList> {
  return apiFetch<WorkflowRunList>(
    `/engagements/${engagementId}/workflows`,
  );
}

export function listWorkflowSteps(
  runId: string,
): Promise<WorkflowStepList> {
  return apiFetch<WorkflowStepList>(`/workflows/${runId}/steps`);
}

export function resumeWorkflow(
  runId: string,
  role: string,
): Promise<WorkflowRun> {
  return apiFetch<WorkflowRun>(`/workflows/${runId}/resume`, {
    method: "POST",
    body: { role },
  });
}
