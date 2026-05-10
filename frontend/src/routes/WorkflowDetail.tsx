import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  getWorkflow,
  listWorkflowSteps,
  resumeWorkflow,
} from "../api/endpoints";
import type { WorkflowRun, WorkflowStepRun } from "../api/types";
import { useAuth } from "../auth/AuthContext";

/**
 * WorkflowDetail — view a single workflow run.
 *
 * Shows current state + step history + (when paused) a Resume
 * button gated on the caller's role matching pause_reason.required_
 * role. Failures surface with the server-side error string.
 */
export function WorkflowDetail() {
  const { runId } = useParams<{ runId: string }>();
  const { user } = useAuth();
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [steps, setSteps] = useState<WorkflowStepRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [resuming, setResuming] = useState(false);

  const refresh = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      const [r, s] = await Promise.all([
        getWorkflow(runId),
        listWorkflowSteps(runId),
      ]);
      setRun(r);
      setSteps(s.steps);
    } catch {
      setError("Failed to load workflow run.");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleResume() {
    if (!runId || !user) return;
    setResuming(true);
    setResumeError(null);
    try {
      await resumeWorkflow(runId, user.role);
      await refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) {
          setResumeError("Your role cannot resume this step.");
        } else if (e.status === 409) {
          setResumeError(
            typeof e.detail === "string" ? e.detail : "Cannot resume.",
          );
        } else {
          setResumeError("Resume failed.");
        }
      }
    } finally {
      setResuming(false);
    }
  }

  if (loading) return <main>Loading...</main>;
  if (error || !run) return <main className="error">{error ?? "Not found"}</main>;

  const canResume =
    run.state === "paused_awaiting_input" &&
    user?.role === run.pause_reason.required_role;

  return (
    <main className="workflow-detail">
      <h1>Workflow run</h1>
      <dl>
        <dt>Template</dt>
        <dd data-testid="run-template">{run.template_id}</dd>
        <dt>Engagement</dt>
        <dd>{run.engagement_id}</dd>
        <dt>State</dt>
        <dd data-testid="run-state">{run.state}</dd>
        <dt>Current step</dt>
        <dd>{run.current_step_index}</dd>
        {run.error && (
          <>
            <dt>Error</dt>
            <dd className="error">{run.error}</dd>
          </>
        )}
      </dl>

      {run.state === "paused_awaiting_input" && (
        <section aria-labelledby="resume-heading">
          <h2 id="resume-heading">Awaiting input</h2>
          <p>
            {run.pause_reason.reason ??
              `Awaiting ${run.pause_reason.required_role}.`}
          </p>
          <button
            onClick={() => void handleResume()}
            disabled={!canResume || resuming}
            data-testid="resume-button"
          >
            {resuming
              ? "Resuming..."
              : canResume
                ? `Resume as ${user?.role}`
                : `Requires ${run.pause_reason.required_role ?? "privileged"} role`}
          </button>
          {resumeError && (
            <p className="error" role="alert">
              {resumeError}
            </p>
          )}
        </section>
      )}

      <section aria-labelledby="steps-heading">
        <h2 id="steps-heading">Step history</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Name</th>
              <th>Type</th>
              <th>State</th>
              <th>Started</th>
              <th>Ended</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s) => (
              <tr key={s.id} data-testid={`step-row-${s.step_name}`}>
                <td>{s.step_index}</td>
                <td>{s.step_name}</td>
                <td>{s.step_type}</td>
                <td>{s.state}</td>
                <td>{s.started_at.slice(0, 19).replace("T", " ")}</td>
                <td>
                  {s.ended_at
                    ? s.ended_at.slice(0, 19).replace("T", " ")
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
