from __future__ import annotations

import base64
import json
import re
from typing import Any

import requests

from config.settings import Settings


class GeminiClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate_json(self, prompt: str) -> Any:
        if not self.settings.gemini_api_key:
            return []

        text = self.generate_text(prompt)
        return json.loads(self._strip_code_fences(text))

    def generate_text(self, prompt: str) -> str:
        if not self.settings.gemini_api_key:
            return ""

        payload = self._generate_content([{"text": prompt}])
        return self._extract_text(payload).strip()

    def generate_text_with_audio(self, prompt: str, audio_bytes: bytes, mime_type: str) -> str:
        if not self.settings.gemini_api_key:
            return ""

        encoded_audio = base64.b64encode(audio_bytes).decode("ascii")
        payload = self._generate_content(
            [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": encoded_audio}},
            ]
        )
        return self._extract_text(payload).strip()

    def _generate_content(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        response = requests.post(
            url,
            params={"key": self.settings.gemini_api_key},
            json={"contents": [{"parts": parts}]},
            timeout=self.settings.request_timeout_seconds,
            verify=self.settings.verify_ssl,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Gemini error {response.status_code}: {response.text[:240]}")
        return response.json()

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        if not candidates:
            return "[]"
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts) or "[]"

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        return text or "[]"
