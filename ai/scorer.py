import json
import time
from datetime import datetime
from typing import Any

import httpx
from openai import OpenAI

from config import AI_CONFIG
from ai.parser import ScoreValidationError, parse_and_validate_score
from ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt


class JobScorer:
    def __init__(self) -> None:
        api_key = AI_CONFIG["api_key"]
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        http_client = httpx.Client(
            timeout=AI_CONFIG["request_timeout_seconds"],
            follow_redirects=True,
        )
        self.client = OpenAI(
            api_key=api_key,
            base_url=AI_CONFIG["base_url"],
            timeout=AI_CONFIG["request_timeout_seconds"],
            http_client=http_client,
        )
        self.model = AI_CONFIG["model"]
        self.temperature = AI_CONFIG["temperature"]
        self.max_tokens = AI_CONFIG["max_tokens"]
        self.max_retries = AI_CONFIG["max_retries"]
        self.retry_delay = AI_CONFIG["retry_delay_seconds"]

    def score_job(self, job_input: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, 1 + self.max_retries):
            try:
                return self._call_api(job_input)
            except ScoreValidationError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    print(
                        f"[score-retry] attempt={attempt}/{self.max_retries} "
                        f"error={exc}"
                    )
                    time.sleep(self.retry_delay)
        raise RuntimeError(
            f"scoring failed after {self.max_retries} retries: {last_error}"
        )

    def _call_api(self, job_input: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(job_input, ensure_ascii=False, indent=2)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(payload)},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        parsed = parse_and_validate_score(content)
        parsed["raw_response"] = {"content": content}
        parsed["score_source"] = "ai"
        parsed["model_name"] = self.model
        parsed["prompt_version"] = PROMPT_VERSION
        parsed["score_status"] = "success"
        parsed["scored_at"] = datetime.utcnow().isoformat(timespec="seconds")
        return parsed
