from deeptutor.agents.question.coordinator import AgentCoordinator


def test_legacy_coordinator_carries_empty_builtin_grant_into_question_context() -> None:
    coordinator = AgentCoordinator(allowed_builtin_tools=[])

    context = coordinator._build_context(user_message="fractions")

    assert context.allowed_builtin_tools == []


def test_legacy_coordinator_carries_explicit_builtin_grant_into_question_context() -> None:
    coordinator = AgentCoordinator(allowed_builtin_tools=["web_fetch"])

    context = coordinator._build_context(user_message="fractions")

    assert context.allowed_builtin_tools == ["web_fetch"]
