from appfactory import logutil
from appfactory.redact import redact


def test_env_secret_values_are_redacted(monkeypatch):
    monkeypatch.setenv("ASC_ISSUER_ID", "69a6de7e-1111-2222-3333-444455556666")
    monkeypatch.setenv("MY_SERVICE_TOKEN", "tok_abcdefghijkl")
    out = redact("issuer=69a6de7e-1111-2222-3333-444455556666 token=tok_abcdefghijkl")
    assert "69a6de7e" not in out and "tok_abc" not in out and out.count("[REDACTED]") == 2


def test_private_key_and_jwt_patterns():
    pem = "-----BEGIN PRIVATE KEY-----\nMIGTAgEAMBMGByqGSM49\n-----END PRIVATE KEY-----"
    jwt = "eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJ4eHh4eHh4In0.c2lnbmF0dXJlc2lnbmF0dXJl"
    out = redact(f"key {pem} bearer: Authorization: Bearer {jwt}")
    assert "MIGTAg" not in out and "eyJhbGci" not in out


def test_log_file_never_contains_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("ASC_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\nSECRETSECRET\n-----END PRIVATE KEY-----")
    log_file = tmp_path / "f.log"
    logutil.set_log_file(log_file)
    try:
        logutil.log("failed with key -----BEGIN PRIVATE KEY-----\nSECRETSECRET\n-----END PRIVATE KEY-----", echo=False)
    finally:
        logutil.set_log_file(None)
    assert "SECRETSECRET" not in log_file.read_text()


def test_paths_are_not_treated_as_secrets(monkeypatch):
    monkeypatch.setenv("ASC_PRIVATE_KEY_PATH", "/Users/me/keys/AuthKey_X.p8")
    assert "/Users/me/keys" in redact("loading /Users/me/keys/AuthKey_X.p8")
