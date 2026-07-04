"""
HTTP session helpers for update checks and resource downloads.
"""

import requests

NO_PROXY = {"http": "", "https": "", "all": ""}


class NoProxySession(requests.Session):
    """A requests session that bypasses proxies without disabling trust_env."""

    def request(
        self,
        method,
        url,
        params=None,
        data=None,
        headers=None,
        cookies=None,
        files=None,
        auth=None,
        timeout=None,
        allow_redirects=True,
        proxies=None,
        hooks=None,
        stream=None,
        verify=None,
        cert=None,
        json=None,
    ):
        request_proxies = dict(proxies or {})
        request_proxies.update(NO_PROXY)
        return super().request(
            method,
            url,
            params=params,
            data=data,
            headers=headers,
            cookies=cookies,
            files=files,
            auth=auth,
            timeout=timeout,
            allow_redirects=allow_redirects,
            proxies=request_proxies,
            hooks=hooks,
            stream=stream,
            verify=verify,
            cert=cert,
            json=json,
        )


def create_no_proxy_session() -> requests.Session:
    return NoProxySession()
