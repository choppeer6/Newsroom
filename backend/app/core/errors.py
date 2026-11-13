class AppError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(code=2001, message=message, http_status=404)


class ConflictError(AppError):
    def __init__(self, message: str = "当前状态不允许该操作") -> None:
        super().__init__(code=2002, message=message, http_status=409)
