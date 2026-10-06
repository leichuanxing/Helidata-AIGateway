"""Validate and print redacted config; available only through container CLI."""
import json
from app.core.config import ConfigurationError, load_settings

if __name__ == '__main__':
    try:
        print(json.dumps(load_settings().model_dump(mode='json'), ensure_ascii=False, indent=2))
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
