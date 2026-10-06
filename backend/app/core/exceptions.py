from fastapi import HTTPException


class APIError(HTTPException):
    def __init__(self, status, code, message):
        super().__init__(status_code=status, detail={'code':code,'message':message})
