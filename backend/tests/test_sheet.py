"""Parser checks for the Google Sheet CSV export and Sheets API values."""

import pytest

from app.sheet import parse_products, parse_values

HEADER = "Nom du produit,Frais psp,TVA,Autres frais,Marge minimum,Marge cible,COGS,Prix de vente,Mult,BE,TARGET,RANGE,Comment"


def test_parses_plain_fractions() -> None:
    csv_text = f"{HEADER}\n2 legging UK + Sleeve,0.07,0,0.01,0.15,0.2,13.8,53.55,x,x,x,x,\n"
    [p] = parse_products(csv_text)
    assert p.name == "2 legging UK + Sleeve"
    assert p.psp_fee == pytest.approx(0.07)
    assert p.cogs == pytest.approx(13.8)
    assert p.selling_price == pytest.approx(53.55)


def test_parses_french_locale_and_percent_signs() -> None:
    csv_text = f'{HEADER}\nLime pour les pieds,"7,00%",0,"1%","0,15","0,2","11,0","39,99",x,x,x,x,\n'
    [p] = parse_products(csv_text)
    assert p.psp_fee == pytest.approx(0.07)
    assert p.other_fees == pytest.approx(0.01)
    assert p.min_margin == pytest.approx(0.15)
    assert p.cogs == pytest.approx(11.0)
    assert p.selling_price == pytest.approx(39.99)


def test_bare_integers_treated_as_percent() -> None:
    csv_text = f"{HEADER}\nProduit,7,0,1,15,20,10,40,x,x,x,x,\n"
    [p] = parse_products(csv_text)
    assert p.psp_fee == pytest.approx(0.07)
    assert p.target_margin == pytest.approx(0.20)


def test_skips_unnamed_partial_and_duplicate_rows() -> None:
    csv_text = (
        f"{HEADER}\n"
        ",0.07,0,0.01,0.15,0.2,18.46,80.39,x,x,x,x,\n"  # no name
        "Real,0.07,0,0.01,0.15,0.2,7.75,29.9,x,x,x,x,\n"
        "Real,0.05,0,0.01,0.15,0.2,9.99,49.9,x,x,x,x,\n"  # duplicate name
        "No price,0.07,0,0.01,0.15,0.2,5.5,,x,x,x,x,\n"
        "Zero cogs,0.07,0,0.01,0.15,0.2,0,29.9,x,x,x,x,\n"
    )
    products = parse_products(csv_text)
    assert [p.name for p in products] == ["Real"]
    assert products[0].cogs == pytest.approx(7.75)


def test_blank_fee_cells_default_to_zero() -> None:
    csv_text = f"{HEADER}\nProduit,,,,,,10,40,x,x,x,x,\n"
    [p] = parse_products(csv_text)
    assert p.psp_fee == 0.0
    assert p.vat == 0.0
    assert p.min_margin == pytest.approx(0.15)
    assert p.target_margin == pytest.approx(0.20)


def test_wrong_tab_shape_yields_nothing() -> None:
    # CALCULATEUR COGS + PV tab: Produit,Bundle,COGS,Prix de vente,%
    csv_text = "Produit,Bundle,COGS,Prix de vente,%\nProduit 1,x1,9,40,0.25\n"
    assert parse_products(csv_text) == []


def test_parse_values_api_rows_jagged_and_typed() -> None:
    # Sheets API UNFORMATTED_VALUE: real numbers, jagged rows, None cells
    values: list[list[object]] = [
        ["Nom du produit", "Frais psp", "TVA", "Autres", "Min", "Cible", "COGS", "Prix"],
        ["2 legging UK + Sleeve", 0.07, 0, 0.01, 0.15, 0.2, 13.8, 53.55, "comment"],
        ["Jagged row"],
        ["Typed as int pct", 7, 0, 1, 15, 20, 10, 40],
        [None, 0.07, 0, 0.01, 0.15, 0.2, 5.5, 30],
    ]
    products = parse_values(values)
    assert [p.name for p in products] == ["2 legging UK + Sleeve", "Typed as int pct"]
    assert products[0].psp_fee == pytest.approx(0.07)
    assert products[0].selling_price == pytest.approx(53.55)
    assert products[1].psp_fee == pytest.approx(0.07)
    assert products[1].other_fees == pytest.approx(0.01)
    assert products[1].target_margin == pytest.approx(0.20)
