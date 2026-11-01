class BrowserAutomationError(Exception):
    """Lỗi chung của browser automation."""


class DriverNotReadyError(BrowserAutomationError):
    """Driver chưa được khởi tạo hoặc không còn hoạt động."""


class ElementNotFoundError(BrowserAutomationError):
    """Không tìm thấy element cần thao tác."""


class ElementActionError(BrowserAutomationError):
    """Không thực hiện được action trên element."""


class StepTransitionError(BrowserAutomationError):
    """Action đã chạy nhưng màn hình kế tiếp không xuất hiện."""