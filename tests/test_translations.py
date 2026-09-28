"""The two translation files must stay in step with each other and with the code."""

import json
import pathlib
import re

FUSION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "fusionsolarplus"
)


def load(language):
    return json.loads(
        (FUSION / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )


def keys(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from keys(value, f"{prefix}{key}.")
    else:
        yield prefix.rstrip(".")


def test_english_and_german_have_the_same_keys():
    en, de = set(keys(load("en"))), set(keys(load("de")))
    assert en - de == set(), "missing in de.json"
    assert de - en == set(), "missing in en.json"


def test_every_translation_key_used_in_code_is_translated():
    entity = load("en")["entity"]
    translated = {key for platform in entity.values() for key in platform}
    used = set()
    for path in FUSION.rglob("*.py"):
        used |= set(
            re.findall(
                r'_attr_translation_key\s*=\s*"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
        )
    assert used, "no translation keys found - the pattern is probably stale"
    assert used - translated == set()


def test_no_translation_is_empty():
    for language in ("en", "de"):
        for key, value in ((k, v) for k, v in _flat(load(language))):
            assert str(value).strip(), f"{language}: {key} is empty"


def _flat(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _flat(value, f"{prefix}{key}.")
    else:
        yield prefix.rstrip("."), node
