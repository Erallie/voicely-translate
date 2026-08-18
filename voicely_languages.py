"""Language-tag normalization and model-response validation."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_language_tag(tag: str) -> str:
    parts = [part for part in tag.strip().replace("_", "-").split("-") if part]
    if not parts:
        return ""
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif (len(part) == 2 and part.isalpha()) or (
            len(part) == 3 and part.isdigit()
        ):
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def parse_languages(value: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in value.split(","):
        tag = normalize_language_tag(part)
        folded = tag.casefold()
        if tag and folded not in seen:
            seen.add(folded)
            result.append(tag)
    return result


def validate_translation_response(
    data: object,
    target_languages: Iterable[str],
) -> dict[str, object]:
    targets = list(target_languages)
    if not targets:
        raise ValueError("At least one target language is required")
    if not isinstance(data, dict):
        raise ValueError("Translation response must be a JSON object")
    returned = normalize_language_tag(str(data.get("original_language", "")))
    original = next(
        (tag for tag in targets if tag.casefold() == returned.casefold()),
        targets[0],
    )
    raw = data.get("translations", {})
    if not isinstance(raw, dict):
        raw = {}
    folded = {str(key).casefold(): str(value).strip() for key, value in raw.items()}
    translations = {
        tag: folded[tag.casefold()]
        for tag in targets
        if tag.casefold() != original.casefold() and tag.casefold() in folded
    }
    return {"original_language": original, "translations": translations}
