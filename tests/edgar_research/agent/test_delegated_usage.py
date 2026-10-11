"""What the research agent's tools spent server-side reaches the caller.

The API reports each request's spend in a header, per model, and the tools
accumulate it per run, so Trading's fundamentals port can log and guard it.
See tests/trading/test_delegated_cost.py for the Trading side.
"""

from __future__ import annotations

import pytest

import app.edgar_research.agent.tools as tools
from app.edgar_research.api import _report_usage
from app.shared.token_usage import (
    USAGE_HEADER,
    TokenUsage,
    decode_usage_header,
    encode_usage_header,
)


class _Resp:
    def __init__(self, headers):
        self.headers = headers


def _header(*usages):
    return _Resp({USAGE_HEADER: encode_usage_header(usages)})


@pytest.fixture(autouse=True)
def _clean_accumulator():
    tools.reset_run_provenance()
    yield
    tools.reset_run_provenance()


def test_usage_reported_by_the_api_is_accumulated_per_model():
    usage = TokenUsage(input_tokens=5158, output_tokens=500)
    tools._record_delegated_usage(_header(("deepseek-v4-flash", usage)))
    tools._record_delegated_usage(_header(("deepseek-v4-flash", usage)))

    total = tools.get_delegated_usage()["deepseek-v4-flash"]
    assert total.input_tokens == 2 * 5158
    assert total.output_tokens == 2 * 500


def test_a_response_without_the_header_is_zero_not_an_error():
    """Endpoints that spend nothing (`/corpus-status`, `/ingest`) send no
    header, and an older server sends none at all. Accounting must not be
    able to fail a run."""
    tools._record_delegated_usage(_Resp({}))
    assert tools.get_delegated_usage() == {}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '{"by_model": [1]}'])
def test_a_malformed_header_is_ignored_rather_than_raised(raw):
    tools._record_delegated_usage(_Resp({USAGE_HEADER: raw}))
    assert tools.get_delegated_usage() == {}


def test_the_accumulator_is_per_run():
    """`reset_run_provenance` already fences every other per-run accumulator
    in this module; usage has to be fenced by the same call or run two would
    be billed for run one."""
    tools._record_delegated_usage(_header(("m", TokenUsage(input_tokens=999))))
    assert tools.get_delegated_usage()
    tools.reset_run_provenance()
    assert tools.get_delegated_usage() == {}


def test_usage_survives_a_json_round_trip_through_the_header():
    usage = TokenUsage(
        input_tokens=1, output_tokens=2, cache_write_tokens=3, cache_read_tokens=4
    )
    assert decode_usage_header(encode_usage_header([("m", usage)])) == {"m": usage}


# ---------------------------------------------------------------------------
# Per-model pricing. Found live 2026-09-11: with /ask and /extract on
# deepseek-v4-flash under a gpt-5.6-luna agent, a bare token total priced at
# the agent's rate logged $0.0375 for ~$0.0666 of real spend.
# ---------------------------------------------------------------------------

def test_one_request_that_spends_on_two_models_reports_both():
    """/ask pays for the answer AND the decomposer, which can be different
    models. Summed before sending, the caller could never price them apart."""
    answer = TokenUsage(input_tokens=5000, output_tokens=400)
    rewrite = TokenUsage(input_tokens=300, output_tokens=60)
    decoded = decode_usage_header(encode_usage_header(
        [("deepseek-v4-flash", answer), ("gpt-5.6-luna", rewrite)]
    ))
    assert decoded == {"deepseek-v4-flash": answer, "gpt-5.6-luna": rewrite}


def test_empty_usage_is_left_out_of_the_header():
    """The decomposer's regex path makes no call; a zero entry would log a
    $0 cost event under a model that was never called."""
    decoded = decode_usage_header(encode_usage_header(
        [("deepseek-v4-flash", TokenUsage(input_tokens=10)), ("gpt-5.6-luna", TokenUsage())]
    ))
    assert list(decoded) == ["deepseek-v4-flash"]


def test_a_legacy_flat_header_is_kept_under_no_model():
    """A server started before this change still sends one bare total. It is
    accounted, not dropped, and the caller prices it at its own model as
    before."""
    legacy = TokenUsage(input_tokens=777).model_dump_json()
    tools._record_delegated_usage(_Resp({USAGE_HEADER: legacy}))
    assert tools.get_delegated_usage() == {None: TokenUsage(input_tokens=777)}


def test_the_server_endpoint_helper_emits_per_model_usage():
    from fastapi import Response

    response = Response()
    _report_usage(
        response,
        ("deepseek-v4-flash", TokenUsage(input_tokens=100)),
        ("gpt-5.6-luna", TokenUsage(output_tokens=7)),
    )
    assert decode_usage_header(response.headers[USAGE_HEADER]) == {
        "deepseek-v4-flash": TokenUsage(input_tokens=100),
        "gpt-5.6-luna": TokenUsage(output_tokens=7),
    }
