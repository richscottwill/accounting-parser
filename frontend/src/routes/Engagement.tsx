import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  listDocuments,
  listWorkflowRuns,
  startWorkflow,
  uploadDocument,
} from "../api/endpoints";
import type {
  DocumentResponse,
  WorkflowRun,
} from "../api/types";

/**
 * Engagement — the central feature view.
 *
 * Composes three panels:
 * - Document list + upload widget (P1.2 ingestion surface).
 * - Workflow runs table with "start monthly_close_bookkeeping" button
 *   (P1.4 workflow surface).
 * - A link into each workflow run for pause/resume + step inspection.
 *
 * Every mutation refetches its associated list; no optimistic UI at
 * P1.5 (premature). Polling is absent; operator clicks refresh.
 * Real-time updates are P2 territory.
 */
export function Engagement() {
  const { engagementId } = useParams<{ engagementId: string }>();
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const refresh = useCallback(async () => {
    if (!engagementId) return;
    setError(null);
    setLoading(true);
    try {
      const [docs, runsResp] = await Promise.all([
        listDocuments(engagementId),
        listWorkflowRuns(engagementId),
      ]);
      setDocuments(docs.documents);
      setRuns(runsResp.runs);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError("Engagement not found for your firm.");
      } else {
        setError("Failed to load engagement.");
      }
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleUpload(file: File) {
    if (!engagementId) return;
    setUploadError(null);
    setUploading(true);
    try {
      await uploadDocument(engagementId, file);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        const detail = e.detail as { existing_document_id?: string } | string;
        if (e.status === 409 && typeof detail === "object" && detail) {
          setUploadError(
            `Duplicate of document ${detail.existing_document_id}.`,
          );
        } else if (e.status === 413) {
          setUploadError("File exceeds upload size limit.");
        } else if (e.status === 415) {
          setUploadError("Unsupported file type.");
        } else if (e.status === 422) {
          setUploadError("Upload rejected by security scan.");
        } else {
          setUploadError("Upload failed.");
        }
      } else {
        setUploadError("Unexpected upload error.");
      }
    } finally {
      setUploading(false);
    }
  }

  async function handleStartWorkflow() {
    if (!engagementId) return;
    try {
      await startWorkflow(engagementId, "monthly_close_bookkeeping");
      await refresh();
    } catch {
      setError("Could not start workflow.");
    }
  }

  if (loading) return <main>Loading...</main>;
  if (error) return <main className="error">{error}</main>;

  return (
    <main className="engagement">
      <h1>Engagement {engagementId}</h1>

      <section aria-labelledby="documents-heading">
        <h2 id="documents-heading">Documents</h2>
        <label className="upload-label">
          Upload a document:
          <input
            type="file"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleUpload(f);
            }}
            disabled={uploading}
            data-testid="upload-input"
          />
        </label>
        {uploadError && (
          <p className="error" role="alert">
            {uploadError}
          </p>
        )}
        {documents.length === 0 ? (
          <p className="muted">No documents uploaded yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Size</th>
                <th>State</th>
                <th>Scan</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((d) => (
                <tr key={d.document_id} data-testid={`doc-row-${d.document_id}`}>
                  <td>{d.filename}</td>
                  <td>{d.content_type}</td>
                  <td>{formatBytes(d.byte_size)}</td>
                  <td>{d.ingest_state}</td>
                  <td>{d.scan_state}</td>
                  <td>{d.uploaded_at.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="workflows-heading">
        <h2 id="workflows-heading">Workflows</h2>
        <button
          onClick={() => void handleStartWorkflow()}
          data-testid="start-workflow"
        >
          Start monthly close
        </button>
        {runs.length === 0 ? (
          <p className="muted">No workflow runs yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Template</th>
                <th>State</th>
                <th>Step</th>
                <th>Required role</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} data-testid={`run-row-${r.run_id}`}>
                  <td>
                    <Link to={`/workflow/${r.run_id}`}>
                      {r.run_id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{r.template_id}</td>
                  <td>{r.state}</td>
                  <td>{r.current_step_index}</td>
                  <td>{r.pause_reason.required_role ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
