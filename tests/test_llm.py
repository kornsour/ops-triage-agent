from triage.agent.prompts import agent_messages, observation_message
from triage.data.db import Ticket
from triage.llm.base import Message, Usage, estimate_cost
from triage.llm.mock import MockProvider


def _ticket(subject: str, body: str, requester: str = "dana@acme.com") -> Ticket:
    return Ticket("TCK-X", subject, body, requester)


def test_mock_first_turn_requests_tools_and_classifies():
    p = MockProvider()
    msgs = agent_messages(_ticket("Locked out of my account", "I'm locked out and can't log in. ASAP."))
    r1 = p.complete(msgs, json_schema={"type": "object"})
    r2 = p.complete(msgs, json_schema={"type": "object"})
    assert r1.text == r2.text  # deterministic
    calls = {c["name"] for c in r1.raw["tool_calls"]}
    # A password lockout should pull runbooks, history, and the directory record.
    assert {"search_runbooks", "lookup_ticket_history", "lookup_user"} <= calls


def test_mock_final_turn_cites_only_observed_runbooks():
    p = MockProvider()
    msgs = agent_messages(_ticket("Locked out", "I'm locked out and can't log in."))
    msgs.append(Message("assistant", '{"tool_calls": []}'))
    msgs.append(observation_message([
        {"tool": "search_runbooks", "result": "[kb-password-reset] Password reset\nDo the thing."}
    ]))
    r = p.complete(msgs, json_schema={"type": "object"})
    final = r.raw["final"]
    assert final["citations"] == ["kb-password-reset"]
    assert final["draft_reply"]
    assert final["recommended_action"] == "reset_password"


def test_mock_usage_tracked_but_free():
    p = MockProvider()
    r = p.complete([Message("user", "hello world")], json_schema={"type": "object"})
    assert r.usage.input_tokens > 0
    assert r.usage.usd == 0.0


def test_negated_urgency_not_high():
    p = MockProvider()
    r = p.complete(agent_messages(_ticket("Laptop screen flickering", "Not urgent, no rush.")),
                   json_schema={"type": "object"})
    # severity is decided at finalize time; re-run the classifier via a second turn
    msgs = agent_messages(_ticket("Laptop screen flickering", "Not urgent, no rush."))
    msgs.append(Message("assistant", "{}"))
    msgs.append(observation_message([{"tool": "search_runbooks", "result": "[kb-hardware-support] x"}]))
    final = p.complete(msgs, json_schema={"type": "object"}).raw["final"]
    assert final["severity"] == "low"
    assert r.raw["tool_calls"]  # first turn still asked for tools


def test_pricing_estimate():
    assert estimate_cost("gpt-4.1", 1_000_000, 0) == 2.0
    assert estimate_cost("claude-opus-4-8", 0, 1_000_000) == 75.0


def test_usage_addition():
    a = Usage(10, 5, 0.01)
    b = Usage(1, 2, 0.02)
    assert (a + b) == Usage(11, 7, 0.03)
