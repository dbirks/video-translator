"""Translation adapters: Protocol + OpenAI GPT-4o implementation."""

import json
import logging
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


@runtime_checkable
class TranslationAdapter(Protocol):
    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "es",
        context_before: str = "",
        context_after: str = "",
    ) -> str:
        """Translate text from source_lang to target_lang."""
        ...


class OpenAITranslationAdapter:
    """Translation adapter using OpenAI GPT-4o."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "es",
        context_before: str = "",
        context_after: str = "",
    ) -> str:
        lang_names = {"en": "English", "es": "Spanish", "fr": "French", "de": "German"}
        source = lang_names.get(source_lang, source_lang)
        target = lang_names.get(target_lang, target_lang)

        system_prompt = (
            f"You are a professional {target} translator specializing in educational and lecture content. "
            f"Translate the given {source} text to {target}. "
            "Preserve the original meaning accurately. Use natural, clear language appropriate for an academic audience. "
            "Do not add, remove, or editorialize content. "
            "The context lines (marked CONTEXT) are for reference only — do NOT translate or include them in your output. "
            "Respond with ONLY the translated text of the main segment, nothing else."
        )

        user_content = ""
        if context_before:
            user_content += f"CONTEXT (previous): {context_before}\n\n"
        user_content += f"TRANSLATE THIS:\n{text}"
        if context_after:
            user_content += f"\n\nCONTEXT (next): {context_after}"

        log.info(f"Translating ({len(text)} chars): {text[:80]}...")

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        translated = response.choices[0].message.content.strip()
        log.info(f"Translation result: {translated[:80]}...")
        return translated


class MockTranslationAdapter:
    """Mock adapter for testing without API keys."""

    async def translate(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "es",
        context_before: str = "",
        context_after: str = "",
    ) -> str:
        return f"[Traducción de: {text}]"
