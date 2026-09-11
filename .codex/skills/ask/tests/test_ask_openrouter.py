import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ask_openrouter.py"
SPEC = importlib.util.spec_from_file_location("ask_openrouter", SCRIPT)
ask_openrouter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ask_openrouter)


class ExtractAnswerTests(unittest.TestCase):
    def test_extracts_string_content(self):
        result = {
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}]
        }
        self.assertEqual(ask_openrouter.extract_answer(result), "answer")

    def test_extracts_structured_text_content(self):
        result = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "first"},
                            {"type": "text", "text": " second"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        self.assertEqual(ask_openrouter.extract_answer(result), "first second")

    def test_uses_later_non_empty_choice(self):
        result = {
            "choices": [
                {"message": {"content": ""}, "finish_reason": "length"},
                {"message": {"content": "answer"}, "finish_reason": "stop"},
            ]
        }
        self.assertEqual(ask_openrouter.extract_answer(result), "answer")

    def test_reports_empty_content_and_finish_reasons(self):
        result = {
            "choices": [
                {
                    "message": {"content": None},
                    "finish_reason": "error",
                    "native_finish_reason": "safety",
                    "error": {"code": 403, "message": "provider rejected request"},
                }
            ]
        }
        with self.assertRaisesRegex(
            ask_openrouter.ResponseError,
            r"empty message\.content; finish_reason=error \(native: safety\); "
            r"error=code=403, message=provider rejected request",
        ):
            ask_openrouter.extract_answer(result)

    def test_reports_top_level_error(self):
        result = {
            "error": {
                "code": 429,
                "message": "rate limited",
                "metadata": {"sensitive": "must not be rendered"},
            }
        }
        with self.assertRaisesRegex(
            ask_openrouter.ResponseError,
            r"OpenRouter error: code=429, message=rate limited$",
        ):
            ask_openrouter.extract_answer(result)

    def test_rejects_missing_or_empty_choices(self):
        for result in ({}, {"choices": []}, {"choices": None}):
            with self.subTest(result=result):
                with self.assertRaisesRegex(
                    ask_openrouter.ResponseError, "response has no choices"
                ):
                    ask_openrouter.extract_answer(result)


if __name__ == "__main__":
    unittest.main()
