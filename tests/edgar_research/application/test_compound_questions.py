"""A question that asks for two different things is decomposed, trigger word or not."""

import pytest

from app.edgar_research.application.query_decomposer import is_compound


@pytest.mark.parametrize("question", [
    "What were Accenture's remaining performance obligations and its cash and cash equivalents at August 31, 2025?",
    "How did Accenture's net cash provided by operating activities and total revenues change between fiscal 2024 and fiscal 2025?",
    "Who audits Broadcom and for how long, and is its internal control over financial reporting effective?",
    "Net cash provided by operating activities and purchases of property and equipment for fiscal 2025",
])
def test_two_different_concepts_joined_by_and_are_compound(question):
    assert is_compound(question)


@pytest.mark.parametrize("question", [
    "What was cash and cash equivalents as of August 31, 2025 and August 31, 2024?",
    "What were net cash provided by operating activities in fiscal 2025 and fiscal 2024?",
    "What was total net revenue in fiscal 2025 compared with fiscal 2024?",
    "Which auditor signed the report and has it changed?",
    "Net cash provided by operating activities, capital expenditures",
    "Did Accenture raise new debt recently?",
])
def test_one_concept_repeated_or_no_and_is_not_compound(question):
    assert not is_compound(question)
