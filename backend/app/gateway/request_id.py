import logging
import uuid
from contextvars import ContextVar

request_id = ContextVar('gateway_request_id', default='-')


def generate():
    return 'req_' + uuid.uuid4().hex


class RequestIDFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'request_id'):
            record.request_id = request_id.get()
        return True


def configure_logging():
    for handler in logging.getLogger().handlers:
        handler.addFilter(RequestIDFilter())
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s'))
