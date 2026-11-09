"""Automated test suite for UC Strategy (Use Cases).
Generated from frozen design: a8_design/UC_DESIGN.json.
Target module: modules.iwd
"""
from datetime import date, timedelta
import pytest
from rest_framework.test import APIClient

from modules.iwd.domain.rules import (
    Priority,
    RequestStatus,
    WorkCategory,
    compute_priority_score,
)
from modules.iwd.models import Contractor, InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_uc_01_submit_maintenance_complaint_main_flow(api):
    """TC_UC_01 | Source: UC-IWD-001 Main Flow
    Employee submits a valid maintenance request and record is persisted in draft state.
    """
    payload = {
        "title": "Air conditioner cooling failure",
        "description": "AC blower runs but compressor does not cool room.",
        "location": "Faculty Cabin 208",
        "category": "electrical",
        "priority": "high",
        "estimated_cost": "3500.00",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_02")
    assert resp.status_code == 201
    assert resp.data["status"] == "draft"
    wr_obj = WorkRequest.objects.get(pk=resp.data["id"])
    assert wr_obj.requester_username == "faculty_02"


@pytest.mark.django_db
def test_tc_uc_02_submit_maintenance_complaint_validation_error(api):
    """TC_UC_02 | Source: UC-IWD-001 Alternative Flow A1
    Submission with empty mandatory fields returns HTTP 400 Bad Request.
    """
    payload = {
        "title": "",
        "description": "Short",
        "location": "",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_02")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_uc_03_track_complaint_status_main_flow(api):
    """TC_UC_03 | Source: UC-IWD-005 Main Flow
    Employee views and tracks status of existing complaints.
    """
    wr = WorkRequest.objects.create(
        title="Door hinge broken",
        description="Main door hinge loose and jammed.",
        location="Hostel 3 Mess",
        category="carpentry",
        priority="medium",
        status="under_review",
        requester_username="warden_h3",
    )
    resp = api.get("/api/v1/iwd/requests/", HTTP_X_USER="warden_h3")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    ids = [item["id"] for item in results]
    assert wr.id in ids


@pytest.mark.django_db
def test_tc_uc_04_assess_complaint_main_flow(api):
    """TC_UC_04 | Source: UC-IWD-002 Main Flow
    Engineer reviews submitted complaint and moves it to under_review state.
    """
    wr = WorkRequest.objects.create(
        title="Fluorescent bulb flickering",
        description="Tube light in seminar room flickers constantly.",
        location="Seminar Hall A",
        category="electrical",
        priority="low",
        status="submitted",
        requester_username="staff_01",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="eng_electrical_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "under_review"


@pytest.mark.django_db
def test_tc_uc_05_prepare_submit_estimate_main_flow(api):
    """TC_UC_05 | Source: UC-IWD-003 Main Flow
    Engineer prepares repair estimate and sets estimated cost and required date.
    """
    wr = WorkRequest.objects.create(
        title="Pathway light pole corroded",
        description="Base of streetlight pole 7 severely corroded.",
        location="Pathway near Library",
        category="electrical",
        priority="high",
        status="under_review",
        requester_username="security_head",
    )
    target_date = (date.today() + timedelta(days=14)).isoformat()
    resp = api.patch(f"/api/v1/iwd/requests/{wr.id}/", {
        "estimated_cost": "18500.00",
        "required_by": target_date,
    }, format="json", HTTP_X_USER="eng_civil_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert float(wr.estimated_cost) == 18500.00


def test_tc_uc_06_flag_urgent_repair_main_flow():
    """TC_UC_06 | Source: UC-IWD-010 Main Flow
    System boosts priority score when urgent priority is specified.
    """
    score_urgent = compute_priority_score(Priority.URGENT, date.today() + timedelta(days=1))
    score_low = compute_priority_score(Priority.LOW, date.today() + timedelta(days=45))
    assert score_urgent > score_low
    assert score_urgent >= 8


@pytest.mark.django_db
def test_tc_uc_07_review_low_cost_estimate_main_flow(api):
    """TC_UC_07 | Source: UC-IWD-003 Exception Flow E1
    Unauthorized actor attempts to approve estimate; verify system rejects with 403 Forbidden.
    """
    wr = WorkRequest.objects.create(
        title="Water filter tap broken",
        description="Drinking water fountain tap leaking continuously.",
        location="Mess Dining Hall",
        category="plumbing",
        priority="low",
        status="under_review",
        requester_username="student_01",
        estimated_cost=1500.00,
    )
    # Under UC-IWD-003 Exception Flow E1, an unauthorized user cannot approve estimate
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {}, format="json", HTTP_X_USER="student_01")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_tc_uc_08_review_estimate_rejection_alternative(api):
    """TC_UC_08 | Source: UC-IWD-003 Alternative Flow A1
    Approving authority rejects request with mandatory rejection reason.
    """
    wr = WorkRequest.objects.create(
        title="Construct executive terrace gazebo",
        description="Build ornamental gazebo on departmental terrace.",
        location="Terrace Core 4",
        category="civil",
        priority="low",
        status="under_review",
        requester_username="emp_20",
        estimated_cost=220000.00,
    )
    rejection_reason = "Out of maintenance scope; submit capital proposal."
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": rejection_reason
    }, format="json", HTTP_X_USER="dept_head")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "rejected"
    assert wr.logs.filter(to_status="rejected", note=rejection_reason).exists()


@pytest.mark.django_db
def test_tc_uc_09_check_stock_material_main_flow(api):
    """TC_UC_09 | Source: UC-IWD-070 Main Flow
    Engineer checks inventory to verify material stock levels.
    """
    item = InventoryItem.objects.create(
        name="LED Bulb 9W",
        unit="pieces",
        quantity_available=15.00,
        unit_cost=90.00,
        minimum_stock=10.00,
    )
    resp = api.get("/api/v1/iwd/inventory/")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    names = [i["name"] for i in results]
    assert item.name in names


@pytest.mark.django_db
def test_tc_uc_10_coordinate_procurement_shortage_main_flow(api):
    """TC_UC_10 | Source: UC-IWD-006 Alternative Flow A1
    Material allocation on work request when stock is depleted must be rejected with 400 Bad Request.
    """
    item = InventoryItem.objects.create(
        name="Gate Valve 2 inch",
        unit="pieces",
        quantity_available=0.00,
        unit_cost=850.00,
        minimum_stock=5.00,
    )
    wr = WorkRequest.objects.create(
        title="Replace gate valve",
        description="Valve seized.",
        location="Pumphouse",
        status="in_progress",
        requester_username="emp_02",
    )
    # Under UC-IWD-006 Alt Flow A1, allocating out-of-stock material must be rejected
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/allocate_material/", {"item_id": item.id, "quantity": 1})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_uc_11_contractor_directory_main_flow(api):
    """TC_UC_11 | Source: UC-IWD-080 Main Flow
    Administrator views accredited contractors list.
    """
    contractor = Contractor.objects.create(
        name="Pioneer Electrical Works",
        registration_number="IWD-CONT-EL-2026",
        contact_person="Ramesh Gupta",
        phone="9811223344",
        email="pioneer@example.com",
        specialization="High Voltage Line Maintenance",
        is_active=True,
    )
    resp = api.get("/api/v1/iwd/contractors/")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    reg_nums = [c["registration_number"] for c in results]
    assert contractor.registration_number in reg_nums


@pytest.mark.django_db
def test_tc_uc_12_execute_repair_work_main_flow(api):
    """TC_UC_12 | Source: UC-IWD-004 Main Flow
    Approved work order transitions to in_progress execution.
    """
    wr = WorkRequest.objects.create(
        title="Fix broken drain cover",
        description="Heavy cast iron drain cover broken outside hostel 1.",
        location="Hostel 1 Quadrangle",
        category="civil",
        priority="high",
        status="approved",
        requester_username="eng_01",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="eng_01")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "in_progress"


@pytest.mark.django_db
def test_tc_uc_13_verify_completed_work_main_flow(api):
    """TC_UC_13 | Source: UC-IWD-007 Main Flow
    Engineer marks physical repair work completed and records actual expenditure.
    """
    wr = WorkRequest.objects.create(
        title="Repair leaking washbasin siphon",
        description="Replace siphon pipe under washbasin 4.",
        location="Hostel 4 Ground Floor Washroom",
        category="plumbing",
        priority="medium",
        status="in_progress",
        requester_username="emp_22",
        estimated_cost=1200.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "1150.00"
    }, format="json", HTTP_X_USER="eng_plumbing_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "completed"
    assert float(wr.actual_cost) == 1150.00


@pytest.mark.django_db
def test_tc_uc_14_close_verified_work_main_flow(api):
    """TC_UC_14 | Source: UC-IWD-008 Main Flow
    Department Head closes verified completed work order.
    """
    wr = WorkRequest.objects.create(
        title="Repaint lecture hall podium",
        description="Wood stain and varnish for main lecture podium.",
        location="Lecture Hall 1",
        category="repair",
        priority="low",
        status="completed",
        requester_username="emp_23",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", HTTP_X_USER="dept_head")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "closed"


@pytest.mark.django_db
def test_tc_uc_15_audit_history_rejected_request_main_flow(api):
    """TC_UC_15 | Source: UC-IWD-191 Main Flow
    Audit history returns chronological progression logs for a work request.
    """
    wr = WorkRequest.objects.create(
        title="Replace switchboard in server room",
        description="Frayed wires in main server room distribution board.",
        location="Server Room 2",
        category="electrical",
        priority="urgent",
        status="draft",
        requester_username="admin_01",
    )
    api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="admin_01")
    resp = api.get(f"/api/v1/iwd/requests/{wr.id}/history/")
    assert resp.status_code == 200
    assert len(resp.data) >= 1
    actions = [log["to_status"] for log in resp.data]
    assert "submitted" in actions
