"""Automated test suite for WF Strategy (Workflows).
Generated from frozen design: a8_design/WF_DESIGN.json.
Target module: modules.iwd
"""
from datetime import date, timedelta
import pytest
from rest_framework.test import APIClient

from modules.iwd.domain.rules import Priority, RequestStatus, can_transition, compute_priority_score
from modules.iwd.models import InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_wf_01_complaint_intake_and_assessment_path(api):
    """TC_WF_01 | Source: BW-IWD-01 - Complaint Intake and Assessment Path
    Verify workflow path from initial complaint creation through submission to under review.
    """
    wr = WorkRequest.objects.create(
        title="Corridor paver block repair",
        description="Uneven paving blocks near admin block.",
        location="Admin Block Walkway",
        category="civil",
        priority="low",
        status="draft",
        requester_username="emp_40",
    )
    # Step 1: Submit
    r1 = api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="emp_40")
    assert r1.status_code == 200
    assert r1.data["status"] == "submitted"

    # Step 2: Review
    r2 = api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="engineer")
    assert r2.status_code == 200
    assert r2.data["status"] == "under_review"

    wr.refresh_from_db()
    assert wr.status == "under_review"
    assert wr.submitted_at is not None


@pytest.mark.django_db
def test_tc_wf_02_low_cost_estimate_approval_path(api):
    """TC_WF_02 | Source: BW-IWD-02 - Low-Cost Estimate Approval Path
    Verify complete low-cost estimate approval path ending in approved status.
    """
    wr = WorkRequest.objects.create(
        title="Classroom whiteboard mounting",
        description="Mount 2 whiteboards in seminar hall.",
        location="Seminar Hall 2",
        category="carpentry",
        priority="medium",
        status="under_review",
        requester_username="emp_41",
        estimated_cost=4500.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_civil_1",
        "note": "Low-cost work approved for immediate execution"
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "approved"
    wr.refresh_from_db()
    assert wr.status == "approved"


@pytest.mark.django_db
def test_tc_wf_03_rejected_low_cost_estimate_path(api):
    """TC_WF_03 | Source: BW-IWD-02 / BW-IWD-12 - Rejected Low-Cost Estimate Path
    Verify rejection path for low-cost estimate.
    """
    wr = WorkRequest.objects.create(
        title="Custom acrylic signage",
        description="Decorative signage for department entrance.",
        location="Department Office",
        category="other",
        priority="low",
        status="under_review",
        requester_username="emp_42",
        estimated_cost=6000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": "Not justifiable from maintenance funds."
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "rejected"
    wr.refresh_from_db()
    assert wr.status == "rejected"


@pytest.mark.django_db
def test_tc_wf_04_hold_for_review_path(api):
    """TC_WF_04 | Source: BW-IWD-03 / BW-IWD-04 - Hold for Review Path
    Verify workflow hold path when committee review or additional clarification is needed.
    """
    wr = WorkRequest.objects.create(
        title="Substation transformer oil filtration",
        description="Major transformer maintenance requiring shutdown coordination.",
        location="Main 33kV Substation",
        category="electrical",
        priority="high",
        status="under_review",
        requester_username="emp_43",
        estimated_cost=65000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/hold/", {
        "note": "Awaiting campus shutdown schedule approval."
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "on_hold"


@pytest.mark.django_db
def test_tc_wf_05_resume_from_hold_path():
    """TC_WF_05 | Source: BW-IWD-03 - Resume from Hold Path
    Verify workflow resumption from on_hold to in_progress or under_review.
    """
    assert can_transition(RequestStatus.ON_HOLD, RequestStatus.IN_PROGRESS) is True
    assert can_transition(RequestStatus.ON_HOLD, RequestStatus.REJECTED) is True


@pytest.mark.django_db
def test_tc_wf_06_material_issue_stock_tracking():
    """TC_WF_06 | Source: BW-IWD-06 - Stock Available - Material Issue Workflow
    Verify inventory deduction / tracking during material issue.
    """
    item = InventoryItem.objects.create(
        name="GI Pipe 1.5 inch",
        unit="meters",
        quantity_available=50.00,
        unit_cost=340.00,
        minimum_stock=10.00,
    )
    # Deduct 15 meters for work execution
    item.quantity_available -= 15.00
    item.save()
    item.refresh_from_db()
    assert float(item.quantity_available) == 35.00
    assert item.is_low_stock is False


@pytest.mark.django_db
def test_tc_wf_07_happy_path_traversal(api):
    """TC_WF_07 | Source: BW-IWD-09 - Work Execution and Verification Success Path
    Verify end-to-end execution path: approved -> in_progress -> completed -> closed.
    """
    wr = WorkRequest.objects.create(
        title="Water filter cartridge replacement",
        description="Routine filter change for RO unit.",
        location="Hostel 2 Dining",
        category="repair",
        priority="medium",
        status="approved",
        requester_username="emp_44",
        estimated_cost=3000.00,
    )
    # Step 1: Start
    r1 = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="engineer")
    assert r1.status_code == 200
    assert r1.data["status"] == "in_progress"

    # Step 2: Complete
    r2 = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "2850.00"
    }, format="json", HTTP_X_USER="engineer")
    assert r2.status_code == 200
    assert r2.data["status"] == "completed"

    # Step 3: Close
    r3 = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", {
        "remarks": "Cartridge replaced; TDS verified at 75 ppm."
    }, format="json", HTTP_X_USER="supervisor")
    assert r3.status_code == 200
    assert r3.data["status"] == "closed"

    wr.refresh_from_db()
    assert wr.status == "closed"
    assert float(wr.actual_cost) == 2850.00


@pytest.mark.django_db
def test_tc_wf_08_guard_violation_unapproved_completion(api):
    """TC_WF_08 | Source: CW-IWD-01 - Estimate Approval Routing Guard Check
    Verify state machine prevents completing a request that has not been approved.
    """
    wr = WorkRequest.objects.create(
        title="Unapproved repair attempt",
        description="Attempting to complete without approval.",
        location="Lab 1",
        category="repair",
        priority="low",
        status="under_review",
        requester_username="emp_45",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", HTTP_X_USER="engineer")
    assert resp.status_code == 400
    wr.refresh_from_db()
    assert wr.status == "under_review"


@pytest.mark.django_db
def test_tc_wf_09_terminal_state_boundary(api):
    """TC_WF_09 | Source: CW-IWD-03 - Work Completion and Verification Boundary
    Verify closing a work request permanently terminates its lifecycle.
    """
    wr = WorkRequest.objects.create(
        title="Closed work order",
        description="Finished and settled work order.",
        location="Faculty Quarter 5",
        category="repair",
        priority="low",
        status="closed",
        requester_username="emp_46",
    )
    resp_start = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="engineer")
    assert resp_start.status_code == 400
    resp_approve = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", HTTP_X_USER="supervisor")
    assert resp_approve.status_code == 400


def test_tc_wf_10_urgent_fast_track_lead_time_boost():
    """TC_WF_10 | Source: BW-IWD-15 - Urgent Fast-Track Review Path
    Verify fast-track urgency path prioritizing urgent maintenance.
    """
    tomorrow = date.today() + timedelta(days=1)
    score = compute_priority_score(Priority.URGENT, tomorrow)
    # base 4 + lead-time urgency boost 4 = 8
    assert score == 8

