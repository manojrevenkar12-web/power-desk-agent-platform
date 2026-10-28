from powerdesk.grounding import Ledger, extract, redact, verify


def ledger() -> Ledger:
    led = Ledger()
    led.add_tool_result("call_1", {"average": 83.03, "volume_mwh": 20274.0, "pnl_eur": 54818.0, "units": {"average": "EUR/MWh", "volume_mwh": "MWh", "pnl_eur": "EUR"}})
    return led


def test_dates_years_and_ids_are_not_numbers_to_check():
    text = "From 1 July 2026 to 2026-08-01, PPA-DE-SOL-01 under EEG §51, in Q3 and W30, 15-minute products."
    assert extract(text) == []


def test_grounded_numbers_pass_and_carry_their_evidence():
    rep = verify("The average was 83.03 EUR/MWh on 20,274 MWh, a P&L of EUR 54,818.", ledger())
    assert rep.ok
    assert all(n["evidence"] for n in rep.as_dict())


def test_rounded_statements_still_match():
    assert verify("About 83 EUR/MWh and 20.3 GWh.", ledger()).ok


def test_an_invented_number_is_caught_and_redacted():
    answer = "The average was 83.03 EUR/MWh. Next month it will be 95.40 EUR/MWh."
    rep = verify(answer, ledger())
    assert not rep.ok
    assert [n.text for n in rep.ungrounded] == ["95.40 EUR/MWh"]
    out = redact(answer, rep)
    assert "95.40" not in out and "83.03" in out


def test_a_unit_mismatch_is_not_grounding():
    rep = verify("The volume was 83.03 MWh.", ledger())
    assert not rep.ok


def test_numbers_from_the_question_are_exempt():
    q = "What if prices rise by 12 EUR/MWh?"
    assert verify("With 12 EUR/MWh more, the average would be above 83.03 EUR/MWh.", ledger(), exempt=[q]).ok
