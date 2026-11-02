"""Automated test suite for UC Strategy (Use Cases).
Generated from frozen design: a8_design/UC_DESIGN.json.
Target module: modules.iwd
"""
from datetime import date, timedelta
import pytest
from rest_framework.test import APIClient

from modules.iwd.domain.rules import Priority, compute_priority_score
from modules.iwd.models import Contractor, InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_uc_01_submit_maintenance_complaint_main_flow(api):
    """TC_UC_01 | Source: UC-IWD-001 Main Flow
    Submit maintenance complaint successfully with complete required parameters.
    """
    payload = {
        "title": "Broken light fixture",
        "description": "Flickering tube light fixture requires starter and tube replacement.",
        "location": "Library 2nd Floor",
        "category": "electrical",
        "priority": "medium",
        "estimated_cost": "800.00",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="prof_gupta")
    assert resp.status_code == 201
    assert resp.data["title"] == payload["title"]
    assert resp.data["status"] == "draft"


@pytest.mark.django_db
def test_tc_uc_02_submit_maintenance_complaint_validation_error(api):
    """TC_UC_02 | Source: UC-IWD-001 Alternative A1 (Validation Error)
    Submit maintenance complaint with missing title and location.
    """
    payload = {
        "title": "",
        "description": "",
        "location": "",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="prof_gupta")
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
        status="submitted",
        requester_username="student_01",
    )
    resp = api.get("/api/v1/iwd/requests/", HTTP_X_USER="student_01")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    assert any(item["id"] == wr.id for item in results)


@pytest.mark.django_db
def test_tc_uc_04_assess_complaint_main_flow(api):
    """TC_UC_04 | Source: UC-IWD-015 Main Flow
    Engineer assesses assigned complaint and advances ticket to under review.
    """
    wr = WorkRequest.objects.create(
        title="Water cooler not cooling",
        description="Compressor makes humming noise but no cooling.",
        location="CSE Department Floor 1",
        category="electrical",
        priority="high",
        status="submitted",
        requester_username="emp_21",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="eng_electrical")
    assert resp.status_code == 200
    assert resp.data["status"] == "under_review"


@pytest.mark.django_db
def test_tc_uc_05_prepare_submit_estimate_main_flow(api):
    """TC_UC_05 | Source: UC-IWD-021 Main Flow
    Engineer prepares and submits repair cost estimate and completion date.
    """
    wr = WorkRequest.objects.create(
        title="Sanitary fittings repair",
        description="Replace flush valve and washers.",
        location="Block D Restrooms",
        category="plumbing",
        priority="medium",
        status="under_review",
        requester_username="emp_22",
    )
    future_date = (date.today() + timedelta(days=10)).isoformat()
    resp = api.patch(f"/api/v1/iwd/requests/{wr.id}/", {
        "estimated_cost": "8500.00",
        "required_by": future_date
    }, format="json", HTTP_X_USER="eng_plumbing")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert float(wr.estimated_cost) == 8500.00


@pytest.mark.django_db
def test_tc_uc_06_flag_urgent_repair_main_flow():
    """TC_UC_06 | Source: UC-IWD-025 Main Flow
    Flag work request as urgent priority.
    """
    tomorrow = date.today() + timedelta(days=1)
    score_urgent = compute_priority_score(Priority.URGENT, tomorrow)
    score_medium = compute_priority_score(Priority.MEDIUM, tomorrow)
    assert score_urgent > score_medium
    assert score_urgent == 8  # base 4 + urgency boost 4


@pytest.mark.django_db
def test_tc_uc_07_review_low_cost_estimate_main_flow(api):
    """TC_UC_07 | Source: UC-IWD-031 Main Flow
    Supervisor reviews and approves low-cost estimate (< Rs. 25,000).
    """
    wr = WorkRequest.objects.create(
        title="Window latch replacement",
        description="Replace broken latches on 4 windows.",
        location="Classroom 104",
        category="carpentry",
        priority="low",
        status="under_review",
        requester_username="emp_23",
        estimated_cost=2200.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_maintenance"
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "approved"
    wr.refresh_from_db()
    assert wr.assigned_to == "eng_maintenance"


@pytest.mark.django_db
def test_tc_uc_08_review_estimate_rejection_alternative(api):
    """TC_UC_08 | Source: UC-IWD-031 Alternative A1 (Rejection)
    Supervisor rejects estimate with justification note.
    """
    wr = WorkRequest.objects.create(
        title="Air conditioner overhaul",
        description="Full compressor replacement proposed.",
        location="Server Room 2",
        category="electrical",
        priority="high",
        status="under_review",
        requester_username="emp_24",
        estimated_cost=45000.00,
    )
    note = "Estimate too high for minor repair; seek warranty coverage."
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": note
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "rejected"
    wr.refresh_from_db()
    assert wr.status == "rejected"


@pytest.mark.django_db
def test_tc_uc_09_check_stock_material_main_flow(api):
    """TC_UC_09 | Source: UC-IWD-061 Main Flow
    Check stock levels and identify available inventory for repair.
    """
    InventoryItem.objects.create(
        name="Copper Wire 2.5 sq mm",
        unit="coils",
        quantity_available=15.00,
        unit_cost=1800.00,
        minimum_stock=3.00,
    )
    resp = api.get("/api/v1/iwd/inventory/")
    assert resp.status_code == 200
    items = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    assert len(items) >= 1
    item = next(i for i in items if i["name"] == "Copper Wire 2.5 sq mm")
    assert float(item["quantity_available"]) == 15.00


@pytest.mark.django_db
def test_tc_uc_10_coordinate_procurement_shortage_main_flow(api):
    """TC_UC_10 | Source: UC-IWD-071 Main Flow
    Query inventory low-stock alerts to coordinate restocking.
    """
    InventoryItem.objects.create(
        name="Gate Valve 2 inch",
        unit="pieces",
        quantity_available=1.00,
        unit_cost=850.00,
        minimum_stock=5.00,
    )
    resp = api.get("/api/v1/iwd/inventory/low_stock/")
    assert resp.status_code == 200
    names = [i["name"] for i in resp.data]
    assert "Gate Valve 2 inch" in names


@pytest.mark.django_db
def test_tc_uc_11_contractor_directory_main_flow(api):
    """TC_UC_11 | Source: UC-IWD-081 Main Flow
    Manage contractor directory and view accredited vendors.
    """
    Contractor.objects.create(
        name="Reliable Plumbing Services",
        registration_number="REG-PLUMB-01",
        contact_person="Ravi Kumar",
        phone="9876500001",
        email="ravi@reliableplumb.com",
        specialization="Commercial Plumbing and Drainage",
        is_active=True,
    )
    resp = api.get("/api/v1/iwd/contractors/")
    assert resp.status_code == 200
    contractors = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    assert any(c["registration_number"] == "REG-PLUMB-01" for c in contractors)


@pytest.mark.django_db
def test_tc_uc_12_execute_repair_work_main_flow(api):
    """TC_UC_12 | Source: UC-IWD-091 Main Flow
    Start physical repair execution.
    """
    wr = WorkRequest.objects.create(
        title="Water line welding",
        description="Weld cracked intake pipeline.",
        location="Pump House 1",
        category="plumbing",
        priority="high",
        status="approved",
        requester_username="emp_25",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="engineer")
    assert resp.status_code == 200
    assert resp.data["status"] == "in_progress"


@pytest.mark.django_db
def test_tc_uc_13_verify_completed_work_main_flow(api):
    """TC_UC_13 | Source: UC-IWD-101 Main Flow
    Complete repair work and record actual cost.
    """
    wr = WorkRequest.objects.create(
        title="Auditorium amplifier repair",
        description="Replace capacitor bank.",
        location="Main Auditorium AV Room",
        category="electrical",
        priority="urgent",
        status="in_progress",
        requester_username="emp_26",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "9200.00"
    }, format="json", HTTP_X_USER="engineer")
    assert resp.status_code == 200
    assert resp.data["status"] == "completed"
    wr.refresh_from_db()
    assert float(wr.actual_cost) == 9200.00


@pytest.mark.django_db
def test_tc_uc_14_close_verified_work_main_flow(api):
    """TC_UC_14 | Source: UC-IWD-111 Main Flow
    Close completed repair ticket following verification.
    """
    wr = WorkRequest.objects.create(
        title="Main gate wheel alignment",
        description="Gate roller off track.",
        location="Campus Gate 1",
        category="repair",
        priority="high",
        status="completed",
        requester_username="security_head",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", {
        "remarks": "Physical inspection satisfactory; gate operating smoothly."
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "closed"


@pytest.mark.django_db
def test_tc_uc_15_audit_history_rejected_request_main_flow(api):
    """TC_UC_15 | Source: UC-IWD-151 Main Flow
    Examine complete transition audit trail for rejected ticket.
    """
    wr = WorkRequest.objects.create(
        title="Carpet installation in faculty lounge",
        description="Provide wall-to-wall carpeting.",
        location="Faculty Lounge",
        category="civil",
        priority="low",
        status="draft",
        requester_username="emp_27",
    )
    api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="emp_27")
    api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {"note": "Disallowed by austerity circular."}, format="json", HTTP_X_USER="supervisor")

    resp = api.get(f"/api/v1/iwd/requests/{wr.id}/history/")
    assert resp.status_code == 200
    to_statuses = [entry["to_status"] for entry in resp.data]
    assert "rejected" in to_statuses
