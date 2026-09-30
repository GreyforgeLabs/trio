class TrioError(Exception):
    def __init__(self, code, message="operation refused", exit_code=3):
        self.code, self.message, self.exit_code = code, message, exit_code
        super().__init__(message)
