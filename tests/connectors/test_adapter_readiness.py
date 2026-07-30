"""GitHub and Slack adapters meet the production-ready contract."""

from twin.connectors import (
    check_adapter_contract,
    production_ready_adapters,
)


def test_github_and_slack_contract_rows_are_ok():
    assert check_adapter_contract("github")["ok"] is True
    assert check_adapter_contract("slack")["ok"] is True


def test_production_ready_reports_two_real_adapters():
    report = production_ready_adapters()
    ready_types = {r["connector_type"] for r in report["ready"]}
    assert "fake" not in ready_types
    assert "github" in ready_types
    assert "slack" in ready_types
    assert report["ready_count"] >= 2
    assert report["ok"] is True
