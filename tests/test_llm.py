from triage.agent.prompts import plan_messages, respond_messages
from triage.llm.base import Message, Usage, estimate_cost
from triage.llm.mock import MockProvider


def test_mock_plan_is_deterministic_and_classifies():
    p = MockProvider()
    msgs = plan_messages("Locked out of my account\nI'm locked out and can't log in. ASAP.", "")
    r1 = p.complete(msgs, json_schema={"type": "object"})
    r2 = p.complete(msgs, json_schema={"type": "object"})
    assert r1.text == r2.text  # deterministic
    assert r1.raw["category"] == "access_password"
    assert r1.raw["severity"] == "high"
    assert r1.raw["recommended_action"] == "reset_password"


def test_mock_respond_cites_context():
    p = MockProvider()
    ctx = "[kb-password-reset] Password reset\nDo the thing."
    r = p.complete(respond_messages("locked out", ctx), json_schema={"type": "object"})
    assert "kb-password-reset" in r.raw["citations"]
    assert r.raw["draft_reply"]


def test_mock_usage_tracked_but_free():
    p = MockProvider()
    r = p.complete([Message("user", "hello world")], json_schema={"type": "object"})
    assert r.usage.input_tokens > 0
    assert r.usage.usd == 0.0


def test_negated_urgency_not_high():
    p = MockProvider()
    r = p.complete(plan_messages("Laptop screen flickering\nNot urgent, no rush.", ""),
                   json_schema={"type": "object"})
    assert r.raw["severity"] == "low"


def test_pricing_estimate():
    assert estimate_cost("gpt-4.1", 1_000_000, 0) == 2.0
    assert estimate_cost("claude-opus-4-8", 0, 1_000_000) == 75.0


def test_usage_addition():
    a = Usage(10, 5, 0.01)
    b = Usage(1, 2, 0.02)
    assert (a + b) == Usage(11, 7, 0.03)
