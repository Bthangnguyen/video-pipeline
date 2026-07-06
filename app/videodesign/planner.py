import re
import uuid

from app.videodesign.schemas import CaptionChunk, ScenePlan, SplitSettings


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "but",
    "by",
    "can",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
    "your",
}


def split_script(script: str, settings: SplitSettings) -> list[ScenePlan]:
    max_words = _soft_word_limit(settings)
    parts = _manual_parts(script) if settings.split_mode == "manual" else _script_parts(script, settings)
    if not parts:
        return []

    scenes: list[ScenePlan] = []
    for part in parts:
        for scene_text in _split_long_part(part, max_words):
            scenes.append(_scene_from_text(scene_text, len(scenes) + 1, settings))
    return scenes


def refresh_scene_orders(scenes: list[ScenePlan]) -> list[ScenePlan]:
    for index, scene in enumerate(scenes, start=1):
        scene.order = index
    return scenes


def estimate_duration(text: str) -> float:
    words = max(1, _word_count(text))
    return round(max(1.5, words / 2.6), 2)


def make_caption_chunks(text: str, duration: float) -> list[CaptionChunk]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    groups = [" ".join(words[index : index + 3]) for index in range(0, len(words), 3)]
    step = duration / len(groups)
    chunks = []
    for index, group in enumerate(groups):
        chunks.append(CaptionChunk(text=group, start=round(index * step, 2), end=round((index + 1) * step, 2)))
    return chunks


def _scene_from_text(text: str, order: int, settings: SplitSettings) -> ScenePlan:
    clean = _clean_text(text)
    duration = min(settings.max_scene_duration_seconds, max(settings.min_scene_duration_seconds, estimate_duration(clean)))
    keywords = _keywords(clean)
    return ScenePlan(
        scene_id=f"scn_{uuid.uuid4().hex}",
        order=order,
        voiceover_text=clean,
        tts_text=clean,
        on_screen_text=_headline(clean),
        caption_text=clean,
        caption_chunks=make_caption_chunks(clean, duration),
        visual_brief=clean,
        matching_keywords=keywords,
        duration_seconds=round(duration, 2),
        template_scene_id="auto",
    )


def _soft_word_limit(settings: SplitSettings) -> int:
    if settings.split_mode == "dense":
        return min(settings.max_words_per_scene, 12)
    if settings.split_mode == "sparse":
        return max(settings.max_words_per_scene, 28)
    return settings.max_words_per_scene


def _manual_parts(script: str) -> list[str]:
    return [_clean_text(part) for part in re.split(r"\n+", script) if _clean_text(part)]


def _script_parts(script: str, settings: SplitSettings) -> list[str]:
    paragraphs = _manual_parts(script)
    parts: list[str] = []
    for paragraph in paragraphs:
        sentences = [_clean_text(part) for part in re.split(r"(?<=[.!?])\s+", paragraph) if _clean_text(part)]
        if settings.split_mode == "sparse":
            parts.extend(_merge_short_sentences(sentences, settings.target_scene_duration_seconds))
        else:
            parts.extend(sentences)
    return parts


def _merge_short_sentences(sentences: list[str], target_seconds: float) -> list[str]:
    target_words = max(1, int(target_seconds * 2.6))
    parts: list[str] = []
    buffer: list[str] = []
    for sentence in sentences:
        buffer.append(sentence)
        if _word_count(" ".join(buffer)) >= target_words:
            parts.append(" ".join(buffer))
            buffer = []
    if buffer:
        parts.append(" ".join(buffer))
    return parts


def _split_long_part(text: str, max_words: int) -> list[str]:
    words = re.findall(r"\S+", text)
    if len(words) <= max_words:
        return [text]
    return [" ".join(words[index : index + max_words]) for index in range(0, len(words), max_words)]


def _headline(text: str) -> str:
    words = re.findall(r"\S+", text)
    headline = " ".join(words[:6])
    return headline.rstrip(".,!?") if headline else ""


def _keywords(text: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9']+", text)]
    selected = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in selected:
            continue
        selected.append(word)
        if len(selected) >= 6:
            break
    if not selected:
        return [text[:80]]
    phrase = " ".join(selected[:5])
    return [phrase, text[:80]]


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
