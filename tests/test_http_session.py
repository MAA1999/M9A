import os
import unittest
from unittest.mock import patch

import requests

from agent.utils.http_session import create_no_proxy_session


class NoProxySessionTest(unittest.TestCase):
    def capture_send_kwargs(self, env):
        captured = {}

        def fake_send(_session, _request, **kwargs):
            captured.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            return response

        with patch.dict(os.environ, env, clear=True):
            with patch.object(requests.Session, "send", fake_send):
                create_no_proxy_session().get("https://example.invalid/manifest.json")

        return captured

    def test_bypasses_environment_proxies_and_preserves_requests_ca_bundle(self):
        captured = self.capture_send_kwargs(
            {
                "HTTP_PROXY": "http://proxy.invalid:8080",
                "HTTPS_PROXY": "http://secure-proxy.invalid:8443",
                "ALL_PROXY": "http://fallback-proxy.invalid:1080",
                "REQUESTS_CA_BUNDLE": "/tmp/custom-ca.pem",
            }
        )

        self.assertEqual(captured["proxies"]["http"], "")
        self.assertEqual(captured["proxies"]["https"], "")
        self.assertEqual(captured["proxies"]["all"], "")
        self.assertEqual(captured["verify"], "/tmp/custom-ca.pem")

    def test_preserves_curl_ca_bundle_fallback(self):
        captured = self.capture_send_kwargs(
            {
                "HTTPS_PROXY": "http://secure-proxy.invalid:8443",
                "CURL_CA_BUNDLE": "/tmp/curl-ca.pem",
            }
        )

        self.assertEqual(captured["proxies"]["https"], "")
        self.assertEqual(captured["verify"], "/tmp/curl-ca.pem")


if __name__ == "__main__":
    unittest.main()
