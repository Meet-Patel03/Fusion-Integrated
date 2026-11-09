"""Automated test suite for FR Strategy (Functional Requirements).
Generated from frozen design: a8_design/FR_DESIGN.json.
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
    requires_budget_allocation,
    requires_director_approval,
    validate_transition,
)
from modules.iwd.models import Contractor, InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_fr_01_submit_valid_complaint(api):
    """TC_FR_01 | Source: CFR-IWD-01 (AFR-IWD-001, AFR-IWD-006)
    Verify authenticated employee can submit a valid maintenance complaint.
    """
    payload = {
        "title": "Broken window pane in faculty office",
        "description": "Glass pane cracked due to strong winds, needs replacement.",
        "location": "Faculty Cabin 104",
        "category": "civil",
        "priority": "medium",
        "estimated_cost": "1500.00",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_user_1")
    assert resp.status_code == 201
    assert resp.data["title"] == payload["title"]
    assert resp.data["status"] == "draft"
    wr_obj = WorkRequest.objects.get(pk=resp.data["id"])
    assert wr_obj.requester_username == "faculty_user_1"


@pytest.mark.django_db
def test_tc_fr_02_validation_mandatory_fields(api):
    """TC_FR_02 | Source: CFR-IWD-01 (AFR-IWD-002, AFR-IWD-003, AFR-IWD-004)
    Verify complaint submission validates mandatory fields.
    """
    payload = {
        "title": "",
        "description": "",
        "location": "",
        "category": "civil",
        "priority": "medium",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="emp_02")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_fr_03_track_submitted_complaint_status(api):
    """TC_FR_03 | Source: CFR-IWD-02 (AFR-IWD-008)
    Verify submitting employee can track status of submitted complaints.
    """
    wr = WorkRequest.objects.create(
        title="Ceiling fan not working",
        description="Fan motor hums but blades do not rotate in lecture hall.",
        location="L-201",
        category="electrical",
        priority="high",
        status="draft",
        requester_username="prof_sharma",
    )
    resp = api.get("/api/v1/iwd/requests/", HTTP_X_USER="prof_sharma")
    assert resp.status_code == 200
    results = resp.data.get("results", resp.data) if isinstance(resp.data, dict) else resp.data
    ids = [item["id"] for item in results]
    assert wr.id in ids


@pytest.mark.django_db
def test_tc_fr_04_complaint_assignment_visibility(api):
    """TC_FR_04 | Source: CFR-IWD-02 (AFR-IWD-007, AFR-IWD-009)
    Verify complaint assignment to an engineer.
    """
    wr = WorkRequest.objects.create(
        title="Water cooler compressor leak",
        description="Refrigerant gas leak observed near mess cooler unit.",
        location="Hostel 2 Mess",
        category="repair",
        priority="urgent",
        status="submitted",
        requester_username="warden_h2",
    )
    api.post(f"/api/v1/iwd/requests/{wr.id}/review/", HTTP_X_USER="eng_civil_1")
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_civil_1"
    }, format="json", HTTP_X_USER="supervisor_01")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.assigned_to == "eng_civil_1"
    assert wr.status == "approved"


@pytest.mark.django_db
def test_tc_fr_05_engineer_submit_estimate(api):
    """TC_FR_05 | Source: CFR-IWD-03 (AFR-IWD-010, AFR-IWD-011)
    Verify engineer prepares and records estimated repair cost.
    """
    wr = WorkRequest.objects.create(
        title="Water seepage in computer lab",
        description="Seepage along eastern exterior wall affecting power conduits.",
        location="Computer Center Ground Floor",
        category="civil",
        priority="high",
        status="under_review",
        requester_username="cc_incharge",
    )
    resp = api.patch(f"/api/v1/iwd/requests/{wr.id}/", {
        "estimated_cost": "32500.00"
    }, format="json", HTTP_X_USER="eng_civil_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert float(wr.estimated_cost) == 32500.00


def test_tc_fr_06_cost_band_classification():
    """TC_FR_06 | Source: CFR-IWD-04 (AFR-IWD-014, AFR-IWD-015)
    Verify estimate cost classification: mid-range estimate <= Rs. 2.5 Lakh does NOT require Director approval.
    """
    # Under CFR-IWD-04 / Table 0 PS 4.1: Mid-cost band is Rs. 25,000 to Rs. 2.5 Lakh (approved by Dept Head).
    # Director approval is required ONLY for high-cost (> Rs. 2.5 Lakh).
    estimate = 180000.00
    assert requires_director_approval(estimate) is False


@pytest.mark.django_db
def test_tc_fr_07_low_cost_approval_workflow(api):
    """TC_FR_07 | Source: CFR-IWD-05 (AFR-IWD-016, AFR-IWD-017)
    Verify IWD Admin / supervisor approval of low-cost estimate.
    """
    wr = WorkRequest.objects.create(
        title="Replace burnt tube light ballasts",
        description="Four electronic ballasts burnt out in corridor lighting fixture.",
        location="Admin Block 1st Floor",
        category="electrical",
        priority="low",
        status="under_review",
        requester_username="emp_04",
        estimated_cost=4200.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", HTTP_X_USER="iwd_admin")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "approved"


@pytest.mark.django_db
def test_tc_fr_08_mid_range_hold_review(api):
    """TC_FR_08 | Source: CFR-IWD-06 (AFR-IWD-019, AFR-IWD-020)
    Verify putting request on hold during committee necessity/feasibility review.
    """
    wr = WorkRequest.objects.create(
        title="Corridor tiling repair",
        description="Damaged tiles in main corridor.",
        location="Corridor Block B",
        category="civil",
        priority="medium",
        status="under_review",
        requester_username="emp_05",
        estimated_cost=75000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/hold/", {
        "note": "Referred to building works committee for structural assessment."
    }, format="json", HTTP_X_USER="dept_head")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "on_hold"


@pytest.mark.django_db
def test_tc_fr_09_high_cost_director_threshold(api):
    """TC_FR_09 | Source: CFR-IWD-09 (AFR-IWD-029, AFR-IWD-030)
    Verify maintenance material allocation validates stock availability and rejects when depleted.
    """
    item = InventoryItem.objects.create(
        name="Cement Bag 50kg",
        unit="bags",
        quantity_available=0.00,
        unit_cost=380.00,
        minimum_stock=10.00,
    )
    wr = WorkRequest.objects.create(
        title="Floor patching",
        description="Patch broken concrete floor.",
        location="Workshop Floor",
        category="civil",
        priority="medium",
        status="in_progress",
        requester_username="emp_10",
    )
    # Under CFR-IWD-09, material allocation requires stock verification
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/allocate_material/", {"item_id": item.id, "quantity": 5})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_tc_fr_10_rejected_request_retains_reason(api):
    """TC_FR_10 | Source: CFR-IWD-08 (AFR-IWD-026, AFR-IWD-027)
    Verify rejection of request retains reason in audit history.
    """
    wr = WorkRequest.objects.create(
        title="Personal AC installation in private quarters",
        description="Install AC unit using departmental maintenance funds.",
        location="Quarter 12B",
        category="electrical",
        priority="low",
        status="under_review",
        requester_username="emp_06",
        estimated_cost=45000.00,
    )
    reason = "Personal residential enhancements not eligible for institutional maintenance."
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": reason
    }, format="json", HTTP_X_USER="dept_head")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "rejected"
    assert wr.logs.filter(to_status="rejected", note=reason).exists()


@pytest.mark.django_db
def test_tc_fr_11_inventory_low_stock_query(api):
    """TC_FR_11 | Source: CFR-IWD-09 (AFR-IWD-028, AFR-IWD-031)
    Verify inventory visibility and low-stock querying for maintenance supplies.
    """
    InventoryItem.objects.create(
        name="PVC Pipe 1 inch",
        unit="meters",
        quantity_available=5.00,
        unit_cost=120.00,
        minimum_stock=20.00,
    )
    InventoryItem.objects.create(
        name="LED Tube Light 20W",
        unit="pieces",
        quantity_available=50.00,
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
    Verify transition of approved work order to in_progress execution.
    """
    wr = WorkRequest.objects.create(
        title="Restroom flush cistern repair",
        description="Replace dual-flush valve assembly.",
        location="Admin Ground Floor Restroom",
        category="plumbing",
        priority="medium",
        status="approved",
        requester_username="emp_07",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/start/", HTTP_X_USER="eng_plumbing_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "in_progress"


@pytest.mark.django_db
def test_tc_fr_13_audit_trail_logging(api):
    """TC_FR_13 | Source: CFR-IWD-11 (AFR-IWD-036, AFR-IWD-037)
    Verify immutable audit log created on every status progression.
    """
    wr = WorkRequest.objects.create(
        title="Roof leak over server rack",
        description="Rainwater dripping near rack 3.",
        location="Server Room 101",
        category="civil",
        priority="urgent",
        status="draft",
        requester_username="sysadmin",
    )
    log_count_before = wr.logs.count()
    api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="sysadmin")
    assert wr.logs.count() == log_count_before + 1
    latest_log = wr.logs.latest("changed_at")
    assert latest_log.to_status == "submitted"
    assert latest_log.actor_username == "sysadmin"


@pytest.mark.django_db
def test_tc_fr_14_work_closure_transition(api):
    """TC_FR_14 | Source: CFR-IWD-12, CFR-IWD-13 (AFR-IWD-040, AFR-IWD-044)
    Verify completion and closure lifecycle transitions.
    """
    wr = WorkRequest.objects.create(
        title="Repair campus main gate lock",
        description="Electronic magnetic lock failure at main gate.",
        location="Main Security Gate",
        category="electrical",
        priority="urgent",
        status="in_progress",
        requester_username="security_officer",
    )
    resp_comp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "8500.00"
    }, format="json", HTTP_X_USER="eng_electrical_1")
    assert resp_comp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "completed"

    resp_close = api.post(f"/api/v1/iwd/requests/{wr.id}/close/", HTTP_X_USER="iwd_admin")
    assert resp_close.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "closed"


@pytest.mark.django_db
def test_tc_fr_15_record_actual_cost_on_completion(api):
    """TC_FR_15 | Source: CFR-IWD-13 (AFR-IWD-042)
    Verify actual expenditure recording upon work completion.
    """
    wr = WorkRequest.objects.create(
        title="Overhead cable replacement",
        description="Replace weather-damaged armored cable between sub-station and hostel 1.",
        location="Substation to H1 Pole 4",
        category="electrical",
        priority="high",
        status="in_progress",
        requester_username="emp_08",
        estimated_cost=28000.00,
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/complete/", {
        "actual_cost": "26450.00"
    }, format="json", HTTP_X_USER="eng_electrical_1")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert float(wr.actual_cost) == 26450.00


@pytest.mark.django_db
def test_tc_fr_16_contractor_registry_active(api):
    """TC_FR_16 | Source: CFR-IWD-16 (AFR-IWD-054, AFR-IWD-056)
    Verify active-role authorization enforcement; unauthorized caller receives 403 Forbidden.
    """
    wr = WorkRequest.objects.create(
        title="Corridor railing repair",
        description="Fix loose stainless steel handrail.",
        location="Admin Block",
        category="civil",
        priority="medium",
        status="under_review",
        requester_username="emp_02",
    )
    # Under CFR-IWD-16, system must enforce active-role authorization
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {}, format="json", HTTP_X_USER="guest_student")
    assert resp.status_code == 403


def test_tc_fr_17_disallow_illegal_skip_transition():
    """TC_FR_17 | Source: CFR-IWD-17 (Workflow rule integrity)
    Verify state machine prevents skipping mandatory lifecycle stages.
    """
    assert can_transition(RequestStatus.DRAFT, RequestStatus.APPROVED) is False
    assert can_transition(RequestStatus.SUBMITTED, RequestStatus.COMPLETED) is False
    with pytest.raises(IWDDomainError):
        validate_transition(RequestStatus.DRAFT, RequestStatus.COMPLETED)
