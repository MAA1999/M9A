# -*- coding: utf-8 -*-

"""
自定义异常类定义
"""


class VersionCheckError(Exception):
    """版本检查基础异常"""

    def __init__(self, message: str, code: int | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ResourceNotFoundError(VersionCheckError):
    """资源不存在异常 (code=8001)"""

    def __init__(self, os_type: str, arch: str):
        message = f"对应架构和系统下的资源不存在 (os={os_type}, arch={arch})"
        super().__init__(message, code=8001)
        self.os_type = os_type
        self.arch = arch


class InvalidOSError(VersionCheckError):
    """无效的系统参数异常 (code=8002)"""

    def __init__(self, os_type: str):
        message = f"错误的系统参数: {os_type}"
        super().__init__(message, code=8002)
        self.os_type = os_type


class InvalidArchError(VersionCheckError):
    """无效的架构参数异常 (code=8003)"""

    def __init__(self, arch: str):
        message = f"错误的架构参数: {arch}"
        super().__init__(message, code=8003)
        self.arch = arch


class InvalidChannelError(VersionCheckError):
    """无效的更新通道参数异常 (code=8004)"""

    def __init__(self, channel: str):
        message = f"错误的更新通道参数: {channel}"
        super().__init__(message, code=8004)
        self.channel = channel


class APIBusinessError(VersionCheckError):
    """API业务逻辑错误 (code>0)"""

    def __init__(self, code: int, msg: str):
        message = f"业务错误 (code={code}): {msg}"
        super().__init__(message, code=code)
        self.api_msg = msg


class APICriticalError(VersionCheckError):
    """API严重错误 (code<0)"""

    def __init__(self, code: int, msg: str):
        message = f"严重错误 (code={code}): {msg}，请联系 Mirror 酱的技术支持"
        super().__init__(message, code=code)
        self.api_msg = msg
