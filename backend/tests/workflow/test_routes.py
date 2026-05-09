"""Workflow HTTP routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.workflow.conftest import SeededEngagement


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_start_workflow_401_without_auth(
    workflow_client: TestClient, seeded_engagement: SeededEngagement
):
    response = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
    )
    assert response.status_code == 401


def test_start_returns_paused_state(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    response = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
        headers=_hdr(preparer_token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "paused_awaiting_input"
    assert body["pause_reason"]["required_role"] == "preparer"


def test_unknown_template_returns_400(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    response = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "not_a_real_template"},
        headers=_hdr(preparer_token),
    )
    assert response.status_code == 400


def test_resume_with_matching_role_completes(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    start = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
        headers=_hdr(preparer_token),
    )
    run_id = start.json()["run_id"]
    resume = workflow_client.post(
        f"/workflows/{run_id}/resume",
        json={"role": "preparer"},
        headers=_hdr(preparer_token),
    )
    assert resume.status_code == 200, resume.text
    assert resume.json()["state"] == "completed"


def test_resume_with_wrong_role_returns_403(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    start = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
        headers=_hdr(preparer_token),
    )
    run_id = start.json()["run_id"]
    # Preparer trying to claim reviewer role.
    resume = workflow_client.post(
        f"/workflows/{run_id}/resume",
        json={"role": "reviewer"},
        headers=_hdr(preparer_token),
    )
    assert resume.status_code == 403


def test_resume_by_user_with_wrong_required_role(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
    reviewer_token: str,
):
    """Run paused for preparer — reviewer user claiming reviewer role
    fails at the runtime check (role != pause's required_role)."""
    start = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
        headers=_hdr(preparer_token),
    )
    run_id = start.json()["run_id"]
    resume = workflow_client.post(
        f"/workflows/{run_id}/resume",
        json={"role": "reviewer"},
        headers=_hdr(reviewer_token),
    )
    # Body check aligns role with caller, but pause needs preparer →
    # service raises ResumeNotAllowedError → 409.
    assert resume.status_code == 409


def test_list_returns_all_runs_for_engagement(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    for _ in range(3):
        workflow_client.post(
            f"/engagements/{seeded_engagement.engagement_id}/workflows",
            json={"template_id": "monthly_close_bookkeeping"},
            headers=_hdr(preparer_token),
        )
    response = workflow_client.get(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        headers=_hdr(preparer_token),
    )
    assert response.status_code == 200
    assert len(response.json()["runs"]) == 3


def test_list_steps(
    workflow_client: TestClient,
    seeded_engagement: SeededEngagement,
    preparer_token: str,
):
    start = workflow_client.post(
        f"/engagements/{seeded_engagement.engagement_id}/workflows",
        json={"template_id": "monthly_close_bookkeeping"},
        headers=_hdr(preparer_token),
    )
    run_id = start.json()["run_id"]
    response = workflow_client.get(
        f"/workflows/{run_id}/steps",
        headers=_hdr(preparer_token),
    )
    assert response.status_code == 200
    steps = response.json()["steps"]
    # parse, classify, validate completed + preparer_review paused.
    assert len(steps) == 4
    assert steps[0]["step_name"] == "parse_source_docs"
    assert steps[-1]["state"] == "paused"
