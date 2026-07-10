from twin.pii import detect, mask


def test_detects_email_and_masks():
    text = "Fale com joao.silva@empresa.com.br sobre o deploy."
    masked, findings = mask(text)
    assert any(f.kind == "email" for f in findings)
    assert "joao.silva@empresa.com.br" not in masked
    assert "[EMAIL_1]" in masked


def test_detects_cpf():
    findings = detect("CPF do cliente: 123.456.789-09")
    assert any(f.kind == "cpf" for f in findings)


def test_detects_api_keys_and_secret_assignments():
    text = "use api_key=sk-abcdefghijklmnop1234 e password: hunter2"
    masked, findings = mask(text)
    kinds = {f.kind for f in findings}
    assert "api_key" in kinds or "secret_assignment" in kinds
    assert "hunter2" not in masked
    assert "sk-abcdefghijklmnop1234" not in masked


def test_clean_text_untouched():
    text = "Decidimos usar FastAPI no backend do Atlas."
    masked, findings = mask(text)
    assert masked == text
    assert findings == []
