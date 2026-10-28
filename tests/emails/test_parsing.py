from pathlib import Path

from centinel.emails.parsing import MAX_TEXT_LENGTH, email_to_text

# Invented email with the layout of a real Yape payment notice.
YAPE_EML = (Path(__file__).parent / "fixtures" / "yape.eml").read_bytes()


def _email(content_type: str, body: str) -> bytes:
    return (
        f"Subject: Test\r\nContent-Type: {content_type}; charset=utf-8\r\n\r\n{body}"
    ).encode()


def test_html_email_keeps_each_cell_on_its_own_line():
    subject, text = email_to_text(YAPE_EML)

    assert subject == "Constancia de pago"
    assert text.splitlines() == [
        "Monto",
        "S/ 20.00",
        "Fecha y hora",
        "27 oct. 2026 - 04:21 pm",
        "Nombre del beneficiario",
        "Edilberto Mac*",
        "Celular del beneficiario",
        "XXXXXXXXXXXX606",
        "Nro. de operación",
        "00000001",
    ]


def test_plain_text_is_preferred_and_tidied():
    _, text = email_to_text(
        _email("text/plain", "Total:   S/ 10.00\r\n\r\n\r\nGracias")
    )

    assert text == "Total: S/ 10.00\nGracias"


def test_long_text_is_cut():
    _, text = email_to_text(_email("text/plain", "x" * (MAX_TEXT_LENGTH + 100)))

    assert len(text) == MAX_TEXT_LENGTH


def test_email_without_text_body_is_empty():
    _, text = email_to_text(_email("image/png", ""))

    assert text == ""
