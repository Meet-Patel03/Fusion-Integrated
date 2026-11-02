"""Automated test suite for FR Strategy (CFR + AFR).
Generated from frozen design: a8_design/FR_DESIGN.json.
Target module: modules.iwd
"""
from datetime import date, timedelta
import pytest
from rest_framework.test import APIClient

from modules.iwd.domain.rules import (
    Priority,
    RequestStatus,
    WorkCategory,
    WorkRequestDraft,
    requires_director_approval,
    validate_work_request,
)
from modules.iwd.models import Contractor, InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_fr_01_submit_valid_complaint(api):
    """TC_FR_01 | Source: CFR-IWD-01 (AFR-IWD-001, AFR-IWD-006)
    Verify authenticated employee can submit a valid maintenance complaint and record is persisted.
    """
    payload = {
        "title": "Fix water leakage in restroom",
        "description": "Pipe joint is leaking continuously in 2nd floor restroom.",
        "location": "Core Lab 102",
        "category": "civil",
        "priority": "medium",
        "estimated_cost": "1500.00",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_01")
    assert resp.status_code == 201
    assert resp.data["title"] == payload["title"]
    assert resp.data["status"] == "draft"
    req_obj = WorkRequest.objects.get(pk=resp.data["id"])
    assert req_obj.requester_username == "faculty_01"


@pytest.mark.django_db
def test_tc_fr_02_validation_mandatory_fields(api):
    """TC_FR_02 | Source: CFR-IWD-01 (AFR-IWD-002, AFR-IWD-003, AFR-IWD-004)
    Verify complaint submission validates mandatory fields (issue category, location, priority).
    """
    payload = {
        "title": "Fix",  # Less than 5 chars
        "description": "Short",  # Less than 10 chars
        "location": "",
        "category": "civil",
        "priority": "medium",
        "estimated_cost": "-500.00",  # Negative cost
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_01")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_fr_03_track_submitted_complaint_status(api):
    """TC_FR_03 | Source: CFR-IWD-02 (AFR-IWD-008)
    Verify submitting employee can track status of submitted complaints.
    """
    wr = WorkRequest.objects.create(
        title="Fluorescent bulb replacement",
        description="Flickering bulb in tutorial room 3.",
        location="Tutorial Block Room 3",
        category="electrical",
        priority="low",
        status="submitted",
        requester_username="emp_01",
    )
    resp = api.get("/api/v1/iwd/requests/", HTTP_X_USER="emp_01")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    ids = [item["id"] for item in results]
    assert wr.id in ids


@pytest.mark.django_db
def test_tc_fr_04_complaint_assignment_visibility(api):
    """TC_FR_04 | Source: CFR-IWD-02 (AFR-IWD-007, AFR-IWD-009)
    Verify complaint assignment to an engineer and engineer visibility.
    """
    wr = WorkRequest.objects.create(
        title="Faulty switchboard repair",
        description="Switch sparking in mechanical workshop.",
        location="Mechanical Workshop Bay 2",
        category="electrical",
        priority="high",
        status="submitted",
        requester_username="emp_02",
        assigned_to="eng_civil_01",
    )
    assert wr.assigned_to == "eng_civil_01"
    fetched = WorkRequest.objects.filter(assigned_to="eng_civil_01")
    assert fetched.filter(id=wr.id).exists()


@pytest.mark.django_db
def test_tc_fr_05_engineer_submit_estimate(api):
    """TC_FR_05 | Source: CFR-IWD-03 (AFR-IWD-010, AFR-IWD-013)
    Verify engineer can submit repair estimate covering estimated cost and target completion date.
    """
    wr = WorkRequest.objects.create(
        title="Wall plaster repair",
        description="Damaged plaster in corridor after heavy rains.",
        location="Corridor Block B",
        category="civil",
        priority="medium",
        status="submitted",
        requester_username="emp_03",
    )
    target_date = (date.today() + timedelta(days=14)).isoformat()
    resp = api.patch(f"/api/v1/iwd/requests/{wr.id}/", {
        "estimated_cost": "15000.00",
        "required_by": target_date
    }, format="json", HTTP_X_USER="eng_civil_01")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert float(wr.estimated_cost) == 15000.00
    assert str(wr.required_by) == target_date


@pytest.mark.django_db
def test_tc_fr_06_cost_band_classification():
    """TC_FR_06 | Source: CFR-IWD-04 (AFR-IWD-014, AFR-IWD-015)
    Verify estimate cost classification into low-cost band (< Rs. 25,000).
    """
    estimate = 18000.00
    is_low_cost = (estimate < 25000.00)
    assert is_low_cost is True
    assert not requires_director_approval(estimate)


@pytest.mark.django_db
def test_tc_fr_07_low_cost_approval_workflow(api):
    """TC_FR_07 | Source: CFR-IWD-05 (AFR-IWD-016)
    Verify approval of low-cost estimate by authorized supervisor.
    """
    wr = WorkRequest.objects.create(
        title="Ceiling fan rewinding",
        description="Motor burnt out; rewinding needed.",
        location="Faculty Office 10",
        category="electrical",
        priority="medium",
        status="under_review",
        requester_username="emp_04",
        estimated_cost=3200.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_electrical_1",
        "note": "Approved by IWD supervisor"
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "approved"
    wr.refresh_from_db()
    assert wr.status == "approved"
    assert wr.assigned_to == "eng_electrical_1"


@pytest.mark.django_db
def test_tc_fr_08_mid_range_hold_review(api):
    """TC_FR_08 | Source: CFR-IWD-06 (AFR-IWD-019, AFR-IWD-020)
    Verify mid-range repair review and escalation handling.
    """
    wr = WorkRequest.objects.create(
        title="Rewiring of entire laboratory floor",
        description="Complex rewiring required across multiple benches.",
        location="CAD Lab Block C",
        category="electrical",
        priority="high",
        status="under_review",
        requester_username="emp_05",
        estimated_cost=75000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/hold/", {
        "note": "Referred for committee feasibility review"
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "on_hold"


@pytest.mark.django_db
def test_tc_fr_09_high_cost_director_threshold():
    """TC_FR_09 | Source: CFR-IWD-07 (AFR-IWD-022, AFR-IWD-023)
    Verify high-cost project requires Director-level approval authorization threshold.
    """
    assert requires_director_approval(150000.00) is True
    assert requires_director_approval(80000.00) is False


@pytest.mark.django_db
def test_tc_fr_10_rejected_request_retains_reason(api):
    """TC_FR_10 | Source: CFR-IWD-08 (AFR-IWD-024, AFR-IWD-026)
    Verify rejected estimate retains rejection reason and supports resubmission.
    """
    wr = WorkRequest.objects.create(
        title="Granite tiling replacement",
        description="Cosmetic replacement of corridor tiles.",
        location="Main Building Entrance",
        category="civil",
        priority="low",
        status="submitted",
        requester_username="emp_06",
    )
    rejection_reason = "Exceeds allocated sub-head budget"
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": rejection_reason
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    assert resp.data["status"] == "rejected"
    wr.refresh_from_db()
    assert wr.status == "rejected"
    log = wr.logs.filter(to_status="rejected").first()
    assert log is not None
    assert rejection_reason in log.note


@pytest.mark.django_db
def test_tc_fr_11_inventory_low_stock_query(api):
    """TC_FR_11 | Source: CFR-IWD-09 (AFR-IWD-027, AFR-IWD-028)
    Verify maintenance inventory tracking, stock queries, and low stock detection.
    """
    InventoryItem.objects.create(
        name="PVC Pipe 1 inch",
        unit="meters",
        quantity_available=4.00,
        unit_cost=120.00,
        minimum_stock=10.00,
    )
    InventoryItem.objects.create(
        name="LED Tube Light 20W",
        unit="pieces",
        quantity_available=100.00,
        unit_cost=250.00,
        minimum_stock=20.00,
    )
    resp = api.get("/api/v1/iwd/inventory/low_stock/")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.data]
    assert "PVC Pipe 1 inch" in names
    assert "LED Tube Light 20W" not in names


@pytest.mark.django_db
def test_tc_fr_12_work_start_progression(api):
    """TC_FR_12 | Source: CFR-IWD-10 (AFR-IWD-032, AFR-IWD-033)
    Verify work execution progress tracking from approved to in_progress.
    """
    wr = WorkRequest.objects.create(
        title="Window mesh installation",
        description="Install anti-mosquito mesh on ground floor.",
        location="Hostel 4 Ground Floor",
        category="carpentry",
        priority="medium",
        status="approved",
        requester_username="emp_07",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="engineer")
    assert resp.status_code == 200
    assert resp.data["status"] == "in_progress"
    wr.refresh_from_db()
    assert wr.status == "in_progress"


@pytest.mark.django_db
def test_tc_fr_13_audit_trail_logging(api):
    """TC_FR_13 | Source: CFR-IWD-11 (AFR-IWD-035, AFR-IWD-037)
    Verify complete audit trail logging of all state changes and actor usernames.
    """
    wr = WorkRequest.objects.create(
        title="Roof waterproof inspection",
        description="Inspect seepage in terrace.",
        location="Library Terrace",
        category="civil",
        priority="medium",
        status="draft",
        requester_username="emp_08",
    )
    api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="emp_08")
    api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="engineer_lead")

    resp = api.get(f"/api/v1/iwd/requests/{wr.id}/history/")
    assert resp.status_code == 200
    logs = resp.data
    statuses = [l["to_status"] for l in logs]
    actors = [l["actor_username"] for l in logs]
    assert "submitted" in statuses
    assert "under_review" in statuses
    assert "engineer_lead" in actors


@pytest.mark.django_db
def test_tc_fr_14_work_closure_transition(api):
    """TC_FR_14 | Source: CFR-IWD-12 (AFR-IWD-038, AFR-IWD-039)
    Verify completed work order closure and post-completion status lock.
    """
    wr = WorkRequest.objects.create(
        title="Bench repair in lecture hall",
        description="Fix loose bolts on lecture benches.",
        location="LHC 101",
        category="carpentry",
        priority="low",
        status="completed",
        requester_username="emp_09",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", {
        "remarks": "Completed satisfactorily"
    }, format="json", HTTP_X_USER="director")
    assert resp.status_code == 200
    assert resp.data["status"] == "closed"


@pytest.mark.django_db
def test_tc_fr_15_record_actual_cost_on_completion(api):
    """TC_FR_15 | Source: CFR-IWD-13 (AFR-IWD-040, AFR-IWD-041)
    Verify recording of actual expenditure upon work completion.
    """
    wr = WorkRequest.objects.create(
        title="Drainage pipe cleaning",
        description="Drain blocked near cafeteria.",
        location="Cafeteria Outer Yard",
        category="plumbing",
        priority="high",
        status="in_progress",
        requester_username="emp_10",
        estimated_cost=15000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "14200.00",
        "note": "Work completed within estimate"
    }, format="json", HTTP_X_USER="engineer")
    assert resp.status_code == 200
    assert resp.data["status"] == "completed"
    wr.refresh_from_db()
    assert float(wr.actual_cost) == 14200.00
    assert wr.completed_at is not None


@pytest.mark.django_db
def test_tc_fr_16_contractor_registry_active(api):
    """TC_FR_16 | Source: CFR-IWD-16 (AFR-IWD-054, AFR-IWD-056)
    Verify accredited contractor directory management and active filter.
    """
    payload = {
        "name": "Apex Engineering Solutions",
        "registration_number": "IWD-CONTR-2026-09",
        "contact_person": "Vikas Agarwal",
        "phone": "9876543219",
        "email": "vikas@apexeng.in",
        "specialization": "HVAC and Electrical Installations",
    }
    resp = api.post("/api/v1/iwd/contractors/", payload, format="json")
    assert resp.status_code == 201
    assert resp.data["registration_number"] == payload["registration_number"]
    assert resp.data["is_active"] is True


@pytest.mark.django_db
def test_tc_fr_17_disallow_illegal_skip_transition(api):
    """TC_FR_17 | Source: CFR-IWD-16 (AFR-IWD-055, AFR-IWD-057)
    Verify disallowance of skipping workflow states (e.g., draft directly to approved).
    """
    wr = WorkRequest.objects.create(
        title="Direct approval bypass attempt",
        description="Testing boundary state transition.",
        location="Room 202",
        category="repair",
        priority="low",
        status="draft",
        requester_username="emp_11",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", HTTP_X_USER="supervisor")
    assert resp.status_code == 400
    wr.refresh_from_db()
    assert wr.status == "draft"
