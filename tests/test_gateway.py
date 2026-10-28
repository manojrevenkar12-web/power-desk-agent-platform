from powerdesk.policy import Context

ARGS = {"ppa": "PPA-DE-SOL-01", "start": "2026-07-01", "end": "2026-08-01"}


def test_allowed_call_runs_and_is_logged_without_arguments(gateway):
    o = gateway.call(Context("lena"), "ppa_valuation", ARGS)
    assert o.ok and o.result["book"] == "origination-de"
    row = gateway.calls.entries[-1]
    assert row["tool"] == "ppa_valuation" and "args_sha256" in row and "PPA-DE-SOL-01" not in str(row)


def test_book_of_another_desk_is_refused_by_policy(gateway):
    o = gateway.call(Context("marc"), "ppa_valuation", ARGS)
    assert not o.ok and o.denied_by and o.result is None


def test_tool_refused_before_arguments_are_even_parsed(gateway):
    o = gateway.call(Context("sofia"), "ppa_valuation", {"ppa": "nonsense"})
    assert not o.ok and o.error.startswith("not permitted")


def test_invalid_arguments_are_explained(gateway):
    o = gateway.call(Context("lena"), "price_stats", {"zone": "XX", "start": "2026-07-01", "end": "2026-08-01"})
    assert not o.ok and "invalid arguments" in o.error


def test_portfolio_with_no_readable_book_is_a_policy_denial(gateway):
    o = gateway.call(Context("ines"), "hedge_report", {"books": ["trading-fr"], "month": "2026-07"})
    assert not o.ok and o.denied_by


def test_unknown_tool(gateway):
    assert gateway.call(Context("lena"), "drop_tables", {}).error == "unknown tool drop_tables"


def test_list_tools_is_filtered(gateway):
    assert {t.name for t in gateway.list_tools(Context("tom"))} == {"price_stats", "negative_prices", "capture_price", "price_drivers", "forecast_error", "search_knowledge"}
    assert len(gateway.list_tools(Context("ravi"))) == 12
