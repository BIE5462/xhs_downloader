class XHSError(Exception):
    """项目基础异常。"""


class DependencyMissingError(XHSError):
    """缺少运行依赖。"""


class AuthExpiredError(XHSError):
    """登录态已失效。"""


class ParseError(XHSError):
    """页面解析失败。"""


class RateLimitedError(XHSError):
    """触发限流或人机验证。"""


class DownloadError(XHSError):
    """下载失败。"""

