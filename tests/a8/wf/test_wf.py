"""Automated test suite for WF Strategy (Workflows).
Generated from frozen design: a8_design/WF_DESIGN.json.
Target module: modules.iwd
"""
from datetime import date, timedelta
import pytest
from rest_framework.test import APIClient

from modules.iwd.domain.rules import (
    IWDDomainError,
    Priority,
    RequestStatus,
    WorkCategory,
    can_transition,
    compute_priority_score,
    validate_transition,
)
from modules.iwd.models import InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_wf_01_complaint_intake_and_assessment_path(api):
    """TC_WF_01 | Source: BW-IWD-01 (Path: Intake -> Assessment)
    Verify sequential workflow: draft -> submitted -> under_review.
    """
    wr = WorkRequest.objects.create(
        title="Fluorescent ballast replacement",
        description="Flickering corridor tube lights outside hall.",
        location="Hall 1 Entrance",
        category="electrical",
        priority="medium",
        status="draft",
        requester_username="emp_20",
    )
    resp_sub = api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="emp_20")
    assert resp_sub.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "submitted"

    resp_rev = api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="eng_electrical_1")
    assert resp_rev.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "under_review"


@pytest.mark.django_db
def test_tc_wf_02_low_cost_estimate_approval_path(api):
    """TC_WF_02 | Source: BW-IWD-03 (Path: Low-Cost Approval)
    Verify estimate approval path under low-cost threshold (< Rs. 25,000).
    """
    wr = WorkRequest.objects.create(
        title="Repair washroom flush valve",
        description="Replace leaking valve seal in faculty block.",
        location="Core 3 2nd Floor",
        category="plumbing",
        priority="low",
        status="under_review",
        requester_username="emp_20",
        estimated_cost=3500.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_plumbing_1"
    }, format="json", HTTP_X_USER="iwd_admin")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "approved"
    assert wr.assigned_to == "eng_plumbing_1"


@pytest.mark.django_db
def test_tc_wf_03_rejected_low_cost_estimate_path(api):
    """TC_WF_03 | Source: BW-IWD-02, WF-IWD-02 (Path: Rejection Decision)
    Verify rejection transition path enforces mandatory justification note (rejects empty note with 400).
    """
    wr = WorkRequest.objects.create(
        title="Install decorative fountain",
        description="Proposal to build ornamental fountain outside hall.",
        location="Hall Courtyard",
        category="civil",
        priority="low",
        status="under_review",
        requester_username="emp_21",
    )
    # Under WF-IWD-02 / BR-IWD-009, rejection transition without a justification note must return 400 Bad Request
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {"note": ""}, format="json", HTTP_X_USER="iwd_admin")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_wf_04_hold_for_review_path(api):
    """TC_WF_04 | Source: BW-IWD-04 (Path: Committee Review / Hold)
    Verify under_review request can transition to on_hold status.
    """
    wr = WorkRequest.objects.create(
        title="Major library HVAC maintenance",
        description="Overhaul central chiller unit in central library.",
        location="Library Plant Room",
        category="electrical",
        priority="high",
        status="under_review",
        requester_username="librarian",
        estimated_cost=85000.00,
    )
    hold_note = "Awaiting committee technical evaluation."
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/hold/", {
        "note": hold_note
    }, format="json", HTTP_X_USER="dept_head")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "on_hold"
    assert wr.logs.filter(to_status="on_hold", note=hold_note).exists()


def test_tc_wf_05_resume_from_hold_path():
    """TC_WF_05 | Source: BW-IWD-04 (Path: Resume from Hold)
    Verify state machine allows resumption from on_hold to in_progress or rejected.
    """
    assert can_transition(RequestStatus.ON_HOLD, RequestStatus.IN_PROGRESS) is True
    assert can_transition(RequestStatus.ON_HOLD, RequestStatus.REJECTED) is True
    assert can_transition(RequestStatus.ON_HOLD, RequestStatus.DRAFT) is False


@pytest.mark.django_db
def test_tc_wf_06_material_issue_stock_tracking(api):
    """TC_WF_06 | Source: BW-IWD-08 (Path: Material Issuance & Low-Stock Tracking)
    Verify inventory query reflects items below minimum stock threshold.
    """
    item = InventoryItem.objects.create(
        name="Ball Bearing 6204",
        unit="pieces",
        quantity_available=2.00,
        unit_cost=150.00,
        minimum_stock=10.00,
    )
    resp = api.get("/api/v1/iwd/inventory/low_stock/")
    assert resp.status_code == 200
    names = [i["name"] for i in resp.data]
    assert item.name in names


@pytest.mark.django_db
def test_tc_wf_07_happy_path_traversal(api):
    """TC_WF_07 | Source: BW-IWD-11, BR-IWD-014 Physical Verification Gate Path
    Verify work request cannot be closed without physical verification (rejects unverified closure with 400).
    """
    wr = WorkRequest.objects.create(
        title="Fix hostel geyser",
        description="Geyser heating coil burnt out.",
        location="Hostel 4 Ground Floor",
        category="electrical",
        priority="high",
        status="completed",
        requester_username="warden_01",
    )
    # Under BW-IWD-11 and BR-IWD-014, closure without physical verification must be rejected
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", format="json", HTTP_X_USER="warden_01")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_wf_08_guard_violation_unapproved_completion(api):
    """TC_WF_08 | Source: BW-IWD-14 (Path: Execution Guard Violation)
    Verify work request cannot jump directly from under_review to completed.
    """
    wr = WorkRequest.objects.create(
        title="Unapproved roof shed",
        description="Shed construction without approval.",
        location="Backyard",
        category="civil",
        priority="low",
        status="under_review",
        requester_username="emp_23",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", format="json", HTTP_X_USER="emp_23")
    assert resp.status_code == 400
    wr.refresh_from_db()
    assert wr.status == "under_review"


@pytest.mark.django_db
def test_tc_wf_09_terminal_state_boundary(api):
    """TC_WF_09 | Source: BW-IWD-15 (Path: Terminal State Boundary)
    Verify terminal states (closed, rejected) disallow any subsequent transitions.
    """
    wr = WorkRequest.objects.create(
        title="Closed routine painting work",
        description="Corridor paint refreshed.",
        location="Corridor 1",
        category="repair",
        priority="low",
        status="closed",
        requester_username="emp_24",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", format="json", HTTP_X_USER="emp_24")
    assert resp.status_code == 400
    wr.refresh_from_db()
    assert wr.status == "closed"


def test_tc_wf_10_urgent_fast_track_lead_time_boost():
    """TC_WF_10 | Source: CW-IWD-02 (Path: Urgent Fast-Track Routing)
    Verify fast-track urgency scoring boosts priority score for short lead times.
    """
    score_emergency = compute_priority_score(Priority.URGENT, date.today() + timedelta(days=1))
    score_standard = compute_priority_score(Priority.URGENT, date.today() + timedelta(days=60))
    assert score_emergency == 8
    assert score_standard == 4
    assert score_emergency > score_standard
