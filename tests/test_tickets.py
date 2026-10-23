import pytest

from blueprint.tickets import parse_csv, ticket_text


def test_parse_csv():
    data = b"date,asset_id,component,action,meter_hours,notes\n2025-01-15,G1,oil filter,replace,1000,dusty\n"
    [t] = parse_csv(data, vendor="Acme")
    assert t.vendor == "Acme" and t.meter_hours == 1000 and t.date.isoformat() == "2025-01-15"
    assert "dusty" in ticket_text(t)


def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="missing columns"):
        parse_csv(b"date,asset_id\n2025-01-01,G1\n")


def test_bad_row_reports_line_number():
    with pytest.raises(ValueError, match="line 2"):
        parse_csv(b"date,asset_id,component,action\nnot-a-date,G1,x,inspect\n")
