"""Select the active classifier from configuration (CLASSIFIER=demo|jev|llm)."""

from __future__ import annotations

from ..app.config import Settings, get_settings
from .classifier import Classifier
from .demo import DemoClassifier
from .jev import JevClassifier
from .llm import LLMClassifier


def get_classifier(settings: Settings | None = None) -> Classifier:
    settings = settings or get_settings()
    choice = settings.classifier.lower()
    if choice == "demo":
        return DemoClassifier()
    if choice == "jev":
        return JevClassifier(
            api_key=settings.jev_api_key, base_url=settings.jev_base_url, model=settings.jev_model
        )
    if choice == "llm":
        return LLMClassifier(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
    raise ValueError(f"unknown CLASSIFIER={settings.classifier!r} (expected demo|jev|llm)")
