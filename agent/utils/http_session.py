"""
HTTP session helpers for update checks and resource downloads.
"""

from typing import Any

import requests  # pyright: ignore[reportMissingModuleSource]

NO_PROXY = {"http": "", "https": "", "all": ""}


class NoProxySession(requests.Session):
    """A requests session that bypasses proxies without disabling trust_env."""

    def request(
        self,
        method: Any,
        url: Any,
        params: Any = None,
        data: Any = None,
        headers: Any = None,
        cookies: Any = None,
        files: Any = None,
        auth: Any = None,
        timeout: Any = None,
        allow_redirects: Any = True,
        proxies: Any = None,
        hooks: Any = None,
        stream: Any = None,
        verify: Any = None,
        cert: Any = None,
        json: Any = None,
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
