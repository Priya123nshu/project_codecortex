from __future__ import annotations

import json

from avatar_service.config import validate_environment
from avatar_service.schemas import model_to_dict


def main() -> None:
    result = validate_environment()
    print(json.dumps(model_to_dict(result), indent=2))
    if result.overall_status == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
