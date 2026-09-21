from __future__ import annotations

import pytest

from server.triage.loader import available_templates, load_template, ruleset_from_dict, load_template_dict

TEMPLATES = ["general", "bankruptcy", "personal_injury", "family_law"]


def test_all_templates_present():
    assert set(TEMPLATES).issubset(set(available_templates()))


@pytest.mark.parametrize("key", TEMPLATES)
def test_template_loads_with_fallback_last(key):
    rs = load_template(key)
    enabled = rs.enabled_rules()
    assert enabled, f"{key} has no enabled rules"
    assert enabled[-1].is_fallback, f"{key} fallback is not last"
    assert rs.questions_to_ask(), f"{key} asks no questions"


@pytest.mark.parametrize("key", TEMPLATES)
def test_template_round_trips(key):
    data = load_template_dict(key)
    rs = ruleset_from_dict(data)
    assert rs.template_key == key
    # Every add_label references a defined label.
    known = rs.label_names()
    for rule in rs.rules:
        for label in rule.actions.add_labels:
            assert label in known, f"{key}: rule {rule.id} adds unknown label {label!r}"


@pytest.mark.parametrize("key", ["bankruptcy", "personal_injury", "family_law"])
def test_practice_templates_add_custom_questions(key):
    rs = load_template(key)
    custom = [k for k, qq in rs.questions.items() if not qq.is_system]
    assert custom, f"{key} defines no custom question"
