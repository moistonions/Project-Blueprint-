"""The tool-using rationale agent, driven by a scripted stand-in for the model (no API calls)."""

from types import SimpleNamespace

from blueprint.config import Settings
from blueprint.llm import AnthropicClient, Tool
from blueprint.models import ExtraWorkStatus
from blueprint.samples import SAMPLE_ASSET, load_samples
from tests.test_pipeline import FakeLLM, bp  # noqa: F401  (fixture)

QUOTE = "Quarry site with heavy dust; radiator fins were half blocked"


class AgentLLM(FakeLLM):
    """Behaves like FakeLLM for extraction, and plays a short tool-calling script for rationales."""

    def __init__(self, invent_quote=False, submit=True):
        super().__init__()
        self.invent_quote, self.submit, self.agent_runs = invent_quote, submit, []

    def run_agent(self, *, model, system, user, tools, max_turns=6):
        by = {t.name: t for t in tools}
        self.agent_runs.append(user)
        found = by["search_field_notes"].run({"query": "radiator fins dust"})
        by["get_oem_requirement"].run({})
        if not self.submit:
            return 2
        quote = "the fins were cleaned because aliens" if self.invent_quote else (QUOTE if QUOTE in found else "")
        by["submit_rationale"].run({"rationale": "Dusty quarry site", "status": "justified",
                                    "conditions": ["dust"], "quotes": [quote] if quote else [], "confidence": 0.9})
        return 3


def radiator(bp):  # noqa: F811
    return next(r for r in bp.db.rationales(SAMPLE_ASSET) if r.task_key.startswith("fin radiator"))


def test_agent_searches_then_submits_a_verified_reason(bp):  # noqa: F811
    bp.llm = AgentLLM()
    load_samples(bp)
    r = radiator(bp)
    assert r.method == "agent" and r.confirmed and r.status == ExtraWorkStatus.JUSTIFIED
    assert r.evidence == [QUOTE]
    assert r.trace[0].startswith('search_field_notes("radiator fins dust")')
    assert r.trace[-1] == "submit_rationale(status=justified)"


def test_agent_quote_not_in_evidence_is_unconfirmed(bp):  # noqa: F811
    bp.llm = AgentLLM(invent_quote=True)
    load_samples(bp)
    r = radiator(bp)
    assert not r.confirmed and r.status == ExtraWorkStatus.UNKNOWN and r.evidence == []


def test_falls_back_to_chain_when_agent_never_submits(bp):  # noqa: F811
    bp.llm = AgentLLM(submit=False)
    load_samples(bp)
    assert radiator(bp).method == "chain"


def test_search_limit_caps_cost(bp):  # noqa: F811
    from blueprint.rationale import MAX_SEARCHES, explain_with_agent

    findings = load_samples(bp)
    extra = next(f for f in findings if f.type.value == "vendor_addition")

    class Greedy:
        def run_agent(self, *, model, system, user, tools, max_turns=6):
            s = {t.name: t for t in tools}["search_field_notes"]
            self.out = [s.run({"query": f"q{i}"}) for i in range(MAX_SEARCHES + 2)]
            return 1

    g = Greedy()
    assert explain_with_agent(g, bp.vectors, extra, model="m") is None
    assert g.out[-1].startswith("Search limit reached")


# --- the Claude client's loop, with the SDK replaced by a stub

class ScriptedMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def use(name, id_, **inp):
    return SimpleNamespace(type="tool_use", name=name, id=id_, input=inp)


def resp(*blocks, stop="tool_use"):
    return SimpleNamespace(stop_reason=stop, stop_details=None, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=100, output_tokens=10))


def test_claude_loop_runs_tools_and_stops_on_submit():
    client = AnthropicClient(Settings(anthropic_api_key="test"))
    msgs = ScriptedMessages([resp(use("search", "t1", query="dust")), resp(use("submit", "t2", answer="ok"))])
    client._client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    got = []
    tools = [Tool("search", "s", {"query": {"type": "string"}}, lambda a: f"found {a['query']}"),
             Tool("submit", "s", {"answer": {"type": "string"}}, lambda a: got.append(a) or "ok", ends_run=True)]
    turns = client.run_agent(model="claude-opus-5-5", system="sys", user="go", tools=tools)
    assert turns == 2 and got == [{"answer": "ok"}]
    second = msgs.calls[1]["messages"]
    assert second[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "found dust",
                                        "is_error": False}
    assert msgs.calls[0]["tools"][0]["strict"] is True
    assert client.usage.calls == 2


def test_claude_loop_reports_tool_errors_and_respects_turn_cap():
    client = AnthropicClient(Settings(anthropic_api_key="test"))
    msgs = ScriptedMessages([resp(use("boom", f"t{i}")) for i in range(3)])
    client._client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))

    def boom(_):
        raise ValueError("bad")

    assert client.run_agent(model="m", system="s", user="u", tools=[Tool("boom", "b", {}, boom)], max_turns=3) == 3
    assert msgs.calls[1]["messages"][2]["content"][0]["is_error"] is True
