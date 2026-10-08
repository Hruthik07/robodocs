from robodocs.collect.notes import redact


def test_redacts_aws_key_and_ip():
    fake_key = "AKIA" + "ABCDEFGHIJKLMNOP"  # assembled at runtime so secret scanners don't flag the repo
    text, counts = redact(f"key {fake_key} on host 54.12.33.201")
    assert "AKIA" not in text and "54.12.33.201" not in text
    assert counts == {"aws_access_key": 1, "ipv4": 1}


def test_redacts_assignment_secret():
    text, _ = redact("GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwxyz123")
    assert "abcdefghijklmnop" not in text


def test_normal_text_untouched():
    src = "Run `python -m train --steps 1000` on Isaac Sim 5.1"
    assert redact(src) == (src, {})
