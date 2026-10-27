"""Exercise the locked transport's hostname verifier without opening sockets."""

import ssl

import boto3
import pytest
from urllib3.connection import _match_hostname
from urllib3.util.ssl_ import resolve_cert_reqs
from urllib3.util.ssl_match_hostname import CertificateError

from agents.search.clients import search_client


def test_native_search_client_accepts_its_hostname_and_rejects_a_different_certificate():
    hostname = "vpc-fixture.eu-west-1.es.amazonaws.com"
    session = boto3.Session(
        aws_access_key_id="test-only", aws_secret_access_key="test-only", region_name="eu-west-1",
    )
    client = search_client(f"https://{hostname}", session)
    try:
        connection = client.transport.get_connection().pool._new_conn()
        assert resolve_cert_reqs(connection.cert_reqs) == ssl.CERT_REQUIRED
        assert connection.assert_hostname is not False
        # This is the same locked urllib3 verifier that raised bool.strip()
        # during the first real managed-domain initialization.
        asserted = connection.assert_hostname or connection.host
        _match_hostname({"subjectAltName": (("DNS", hostname),)}, asserted)
        with pytest.raises(CertificateError):
            _match_hostname({"subjectAltName": (("DNS", "different.example.org"),)}, asserted)
    finally:
        client.close()
