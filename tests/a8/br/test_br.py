"""Automated test suite for BR Strategy (Business Rules).
Generated from frozen design: a8_design/BR_DESIGN.json.
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
    requires_budget_allocation,
    requires_director_approval,
    validate_transition,
)
from modules.iwd.models import InventoryItem, WorkRequest, WorkRequestLog


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_tc_br_01_active_role_authorization(api):
    """TC_BR_01 | Source: BR-IWD-001 - Active-role authorization
    Ensure work request creation validates requester identity and requires valid user.
    """
    payload = {
        "title": "Fix classroom lighting circuit",
        "description": "Circuit breaker trips upon switching on lights.",
        "location": "LH 201",
        "category": "electrical",
        "priority": "high",
        "estimated_cost": "2000.00",
    }
    resp = api.post("/api/v1/iwd/requests/", payload, format="json", HTTP_X_USER="faculty_01")
    assert resp.status_code == 201
    req_obj = WorkRequest.objects.get(pk=resp.data["id"])
    assert req_obj.requester_username == "faculty_01"


@pytest.mark.django_db
def test_tc_br_02_automatic_engineer_assignment(api):
    """TC_BR_02 | Source: BR-IWD-002 - Automatic engineer assignment
    Verify assigned_to can be designated during triage or approval.
    """
    wr = WorkRequest.objects.create(
        title="Sanitary line leakage",
        description="Drain leakage in staff quarters block 2.",
        location="Staff Quarter 2B",
        category="plumbing",
        priority="medium",
        status="under_review",
        requester_username="emp_30",
    )
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/approve/", {
        "assigned_to": "eng_electrical_1"
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.assigned_to == "eng_electrical_1"


def test_tc_br_03_cost_band_routing_low_cost():
    """TC_BR_03 | Source: BR-IWD-003 - Cost-band routing (< Rs. 25,000 low-cost band)
    Verify low-cost threshold check (< Rs. 25,000) for standard maintenance.
    """
    estimate = 24000.00
    assert not requires_budget_allocation(WorkCategory.REPAIR, estimate)
    assert not requires_director_approval(estimate)


def test_tc_br_04_cost_band_routing_high_cost_upper_threshold():
    """TC_BR_04 | Source: BR-IWD-003 - Cost-band routing (> Rs. 1,00,000 high-cost threshold)
    Verify high-cost threshold check (> Rs. 1,00,000) requiring Director authorization.
    """
    assert requires_director_approval(125000.00) is True


def test_tc_br_05_cost_band_routing_boundary_lower_threshold():
    """TC_BR_05 | Source: BR-IWD-003 - Cost-band routing (<= Rs. 1,00,000 boundary)
    Verify estimate <= Rs. 1,00,000 does not require Director escalation.
    """
    assert requires_director_approval(100000.00) is False
    assert requires_director_approval(99999.00) is False


def test_tc_br_06_high_cost_bidding_budget_rule():
    """TC_BR_06 | Source: BR-IWD-007 - High-cost bidding authorization (> Rs. 5,00,000 capital budget rule)
    Verify projects > Rs. 5,00,000 require formal budget allocation.
    """
    assert requires_budget_allocation(WorkCategory.CIVIL, 600000.00) is True
    assert requires_budget_allocation(WorkCategory.CIVIL, 400000.00) is False


def test_tc_br_07_new_construction_budget_rule():
    """TC_BR_07 | Source: BR-IWD-007 - New construction budget rule
    Verify new construction projects always require budget allocation regardless of cost.
    """
    assert requires_budget_allocation(WorkCategory.NEW_CONSTRUCTION, 50000.00) is True
    assert requires_budget_allocation(WorkCategory.NEW_CONSTRUCTION, 500.00) is True


@pytest.mark.django_db
def test_tc_br_08_rejection_reason_persistence(api):
    """TC_BR_08 | Source: BR-IWD-009 - Rejection reason and resubmission
    Verify rejection transitions cleanly and records mandatory reason note.
    """
    wr = WorkRequest.objects.create(
        title="Excessive lab partition wall",
        description="Construct new partition in faculty lab.",
        location="Lab 3",
        category="civil",
        priority="low",
        status="under_review",
        requester_username="emp_31",
    )
    rejection_note = "Scope unclear; revise specification and reduce footprint."
    resp = api.post(f"/api/v1/iwd/requests/{wr.id}/reject/", {
        "note": rejection_note
    }, format="json", HTTP_X_USER="supervisor")
    assert resp.status_code == 200
    wr.refresh_from_db()
    assert wr.status == "rejected"
    assert wr.logs.filter(to_status="rejected", note=rejection_note).exists()


@pytest.mark.django_db
def test_tc_br_09_inventory_low_stock_trigger():
    """TC_BR_09 | Source: BR-IWD-010 - Inventory low-stock rule
    Verify inventory stock triggers low-stock indicator when quantity <= minimum_stock.
    """
    item = InventoryItem(
        name="Circuit Breaker 16A",
        unit="pieces",
        quantity_available=5.00,
        unit_cost=320.00,
        minimum_stock=10.00,
    )
    assert item.is_low_stock is True


@pytest.mark.django_db
def test_tc_br_10_inventory_adequate_stock_trigger():
    """TC_BR_10 | Source: BR-IWD-010 - Inventory adequate stock rule
    Verify inventory item does not trigger alert when quantity > minimum_stock.
    """
    item = InventoryItem(
        name="Cable Ties Pack",
        unit="packs",
        quantity_available=25.00,
        unit_cost=80.00,
        minimum_stock=10.00,
    )
    assert item.is_low_stock is False


def test_tc_br_11_urgent_priority_scoring_acceleration():
    """TC_BR_11 | Source: BR-IWD-012 - Urgent priority scoring acceleration
    Verify urgent priority tickets receive accelerated priority score.
    """
    urgent_score = compute_priority_score(Priority.URGENT, None)
    low_score = compute_priority_score(Priority.LOW, None)
    assert urgent_score == 4
    assert low_score == 1
    assert urgent_score > low_score


@pytest.mark.django_db
def test_tc_br_12_audit_logging_decision_trail(api):
    """TC_BR_12 | Source: BR-IWD-013 - Audit logging of decisions
    Verify every state change creates an audit log entry in iwd_work_request_log.
    """
    wr = WorkRequest.objects.create(
        title="Overhead tank valve replacement",
        description="Replace rusty brass gate valve.",
        location="Hostel 1 Overhead Tank",
        category="plumbing",
        priority="high",
        status="draft",
        requester_username="emp_32",
    )
    initial_log_count = wr.logs.count()
    api.post(f"/api/v1/iwd/requests/{wr.id}/submit/", HTTP_X_USER="emp_32")
    assert wr.logs.count() == initial_log_count + 1
    latest_log = wr.logs.latest("changed_at")
    assert latest_log.from_status == "draft"
    assert latest_log.to_status == "submitted"


def test_tc_br_13_illegal_transition_rejection():
    """TC_BR_13 | Source: BR-IWD-014 - State transition legality validation
    Verify illegal transition throws IWDDomainError (cannot jump from submitted to completed).
    """
    with pytest.raises(IWDDomainError):
        validate_transition(RequestStatus.SUBMITTED, RequestStatus.COMPLETED)


def test_tc_br_14_closed_state_is_terminal():
    """TC_BR_14 | Source: BR-IWD-014 - Closed state is terminal
    Verify closed state has no legal outgoing transitions.
    """
    for target in RequestStatus:
        assert can_transition(RequestStatus.CLOSED, target) is False

