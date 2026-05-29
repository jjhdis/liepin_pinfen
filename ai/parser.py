import json
from typing import Any


VALID_VERDICTS = {"apply", "apply_with_caution", "skip"}


class ScoreValidationError(ValueError):
    pass


def parse_and_validate_score(raw_content: str) -> dict[str, Any]:
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ScoreValidationError(f"model did not return valid JSON: {exc}") from exc

    required_int_fields = {
        "score_activity": (0, 30),
        "score_jd": (0, 25),
        "score_company": (0, 20),
        "score_salary": (0, 15),
        "score_other": (0, 10),
        "total": (0, 100),
    }

    for field, (minimum, maximum) in required_int_fields.items():
        if field not in data:
            raise ScoreValidationError(f"missing field: {field}")
        if not isinstance(data[field], int):
            raise ScoreValidationError(f"field must be int: {field}")
        if not minimum <= data[field] <= maximum:
            raise ScoreValidationError(f"field out of range: {field}")

    expected_total = (
        data["score_activity"]
        + data["score_jd"]
        + data["score_company"]
        + data["score_salary"]
        + data["score_other"]
    )
    if data["total"] != expected_total:
        raise ScoreValidationError("total does not match component scores")

    verdict = data.get("verdict")
    if verdict not in VALID_VERDICTS:
        raise ScoreValidationError("invalid verdict")

    red_flags = data.get("red_flags")
    if not isinstance(red_flags, list):
        raise ScoreValidationError("red_flags must be a list")
    data["red_flags"] = [str(item).strip() for item in red_flags if str(item).strip()][:3]

    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ScoreValidationError("reasoning must be a non-empty string")
    data["reasoning"] = reasoning.strip()[:200]

    return data
