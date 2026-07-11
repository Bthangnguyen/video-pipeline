import re

from app.videodesign.errors import INVALID_PROJECT_INPUT, SCRIPT_GENERATION_FAILED, VideoDesignError
from app.videodesign.schemas import (
    MaterialSearchGroup,
    MaterialSearchPlan,
    MaterialsSearchRequest,
    ScenePlan,
    VideoDesignProject,
)


KEYWORD_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "any",
    "are",
    "because",
    "but",
    "can",
    "could",
    "did",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "his",
    "how",
    "into",
    "its",
    "just",
    "not",
    "now",
    "off",
    "our",
    "out",
    "over",
    "she",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "this",
    "too",
    "was",
    "what",
    "when",
    "will",
    "with",
    "you",
    "your",
}


PINTEREST_QUERY_DROP_WORDS = {
    "4k",
    "aesthetic",
    "cinematic",
    "close",
    "hd",
    "shot",
    "shocking",
    "trending",
    "up",
    "vertical",
    "viral",
}


DOUYIN_QUERY_DROP_TERMS = ("科普", "解说", "盘点", "合集", "教程", "文案", "语录", "混剪", "剪辑")


DOUYIN_QUERY_REPLACEMENTS = {
    "玄関": "玄关",
    "実写": "实拍",
    "子供": "孩子",
    "靴下": "袜子",
    "畳": "榻榻米",
    "足元": "脚下",
}


VISUAL_QUERY_GENERIC_TOKENS = {
    "4k",
    "broll",
    "cinematic",
    "daily",
    "footage",
    "raw",
    "real",
    "scene",
    "shot",
    "video",
    "vertical",
}


VISUAL_TOKEN_ALIASES = {
    "canine": "dog",
    "cats": "cat",
    "children": "child",
    "dogs": "dog",
    "feline": "cat",
    "husband": "couple",
    "husbands": "couple",
    "japanese": "japan",
    "kids": "child",
    "kittens": "cat",
    "partners": "couple",
    "puppies": "dog",
    "shoes": "shoe",
    "spouse": "couple",
    "spouses": "couple",
    "wife": "couple",
    "wives": "couple",
}


def _reset_material_search_plan(project: VideoDesignProject) -> None:
    project.material_search_plan = MaterialSearchPlan(
        popular_first=project.material_search_plan.popular_first,
    )


def _normalize_keywords(keywords, limit: int) -> list[str]:
    normalized = []
    for keyword in keywords or []:
        value = re.sub(r"\s+", " ", str(keyword)).strip(" ,.;:-")
        if not value or value.lower() in {item.lower() for item in normalized}:
            continue
        normalized.append(value[:120])
        if len(normalized) >= max(1, limit):
            break
    return normalized


def _fallback_keywords_for_scene(project: VideoDesignProject, scene: ScenePlan, limit: int) -> list[str]:
    candidates = []
    for text in (scene.visual_brief, scene.on_screen_text, scene.voiceover_text, project.idea, project.script):
        phrase = _keyword_phrase(text)
        if phrase:
            if "video" not in phrase and "footage" not in phrase:
                _append_keyword(candidates, f"{phrase} raw footage")
            _append_keyword(candidates, phrase)
        if len(candidates) >= max(1, limit):
            break
    return candidates[: max(1, limit)] or ["raw vertical footage"]


def _normalize_generated_material_search_plan(
    project: VideoDesignProject,
    scenes: list[ScenePlan],
    data: dict,
) -> tuple[MaterialSearchPlan, list[dict]]:
    selected_ids = {scene.scene_id for scene in scenes}
    errors: list[dict] = []
    groups: list[MaterialSearchGroup] = []
    assigned: set[str] = set()
    raw_groups = [item for item in data.get("groups", []) if isinstance(item, dict)]
    role_priority = {"exact": 0, "hook": 1, "base": 2}
    raw_groups.sort(key=lambda item: role_priority.get(str(item.get("role") or "base").lower(), 2))

    used_ids: set[str] = set()
    for item in raw_groups:
        role = str(item.get("role") or "base").lower()
        if role not in {"hook", "base", "exact"}:
            role = "base"
        scene_ids = []
        for scene_id in item.get("scene_ids") or []:
            value = str(scene_id or "")
            if value not in selected_ids or value in assigned:
                continue
            scene_ids.append(value)
        if not scene_ids:
            continue

        exact_subject = _first_text(item.get("exact_subject")) if role == "exact" else ""
        label = _first_text(item.get("label"), exact_subject, role.title())
        douyin_keyword = _normalize_douyin_visual_query(item.get("douyin_keyword", ""))
        pinterest_keyword = _normalize_pinterest_visual_query(item.get("pinterest_keyword", ""))
        if not douyin_keyword:
            douyin_keyword = _first_text(pinterest_keyword, _project_base_keyword(project, scenes))
        if not pinterest_keyword:
            pinterest_keyword = _normalize_pinterest_visual_query(_first_text(exact_subject, label, _project_base_keyword(project, scenes)))
        if not douyin_keyword or not pinterest_keyword:
            errors.extend(
                {
                    "scene_id": scene_id,
                    "error": {
                        "code": SCRIPT_GENERATION_FAILED,
                        "message": "DeepSeek returned a search group without usable source keywords.",
                        "retryable": True,
                    },
                }
                for scene_id in scene_ids
            )
            continue
        if not _generated_search_group_is_grounded(project, scenes, label, exact_subject, pinterest_keyword):
            errors.extend(
                {
                    "scene_id": scene_id,
                    "error": {
                        "code": SCRIPT_GENERATION_FAILED,
                        "message": "DeepSeek returned an ungrounded search group, so the scene was assigned to base footage.",
                        "retryable": True,
                    },
                }
                for scene_id in scene_ids
            )
            continue

        group_id = _unique_search_group_id(role, exact_subject or label, used_ids)
        groups.append(
            MaterialSearchGroup(
                group_id=group_id,
                role=role,
                label=label,
                exact_subject=exact_subject,
                douyin_keyword=douyin_keyword,
                pinterest_keyword=pinterest_keyword,
                douyin_fallback=_normalize_douyin_visual_query(item.get("douyin_fallback", "")),
                pinterest_fallback=_normalize_pinterest_visual_query(item.get("pinterest_fallback", "")),
                scene_ids=scene_ids,
            )
        )
        assigned.update(scene_ids)

    missing_ids = [scene.scene_id for scene in scenes if scene.scene_id not in assigned]
    if missing_ids:
        base = next((group for group in groups if group.role == "base"), None)
        if not base:
            base = _fallback_material_search_group(project, scenes, missing_ids)
            groups.append(base)
        else:
            base.scene_ids.extend(missing_ids)
        errors.extend(
            {
                "scene_id": scene_id,
                "error": {
                    "code": SCRIPT_GENERATION_FAILED,
                    "message": "DeepSeek omitted this scene, so it was assigned to the shared base group.",
                    "retryable": True,
                },
            }
            for scene_id in missing_ids
        )

    plan = MaterialSearchPlan(popular_first=project.material_search_plan.popular_first, groups=groups)
    return _normalize_user_material_search_plan_for_scenes(project, plan, selected_ids), errors


def _generated_search_group_is_grounded(
    project: VideoDesignProject,
    scenes: list[ScenePlan],
    label: str,
    exact_subject: str,
    pinterest_keyword: str,
) -> bool:
    context = " ".join(
        [
            project.idea,
            project.script,
            *(scene.voiceover_text for scene in scenes),
            *(scene.visual_brief for scene in scenes),
        ]
    )
    context_tokens = _visual_grounding_tokens(context)
    group_tokens = _visual_grounding_tokens(" ".join([label, exact_subject, pinterest_keyword]))
    return bool(context_tokens and group_tokens and context_tokens.intersection(group_tokens))


def _material_search_plan_from_scene_plans(
    project: VideoDesignProject,
    scenes: list[ScenePlan],
) -> MaterialSearchPlan:
    groups: list[MaterialSearchGroup] = []
    grouped: dict[tuple[str, str, str], MaterialSearchGroup] = {}
    used_ids: set[str] = set()
    for scene in scenes:
        plan = scene.visual_search_plan or _fallback_visual_search_plan_from_keywords(
            scene,
            scene.matching_keywords or _fallback_keywords_for_scene(project, scene, 3),
        )
        role = "hook" if scene.order == 1 and plan.get("retention_role") == "hook" else "base"
        douyin_keyword = _first_text(plan.get("douyin_primary_keyword"), *scene.matching_keywords)
        pinterest_keyword = _first_text(plan.get("pinterest_primary_keyword"), *scene.matching_keywords)
        key = (role, douyin_keyword.lower(), pinterest_keyword.lower())
        group = grouped.get(key)
        if not group:
            group = MaterialSearchGroup(
                group_id=_unique_search_group_id(role, plan.get("content_anchor") or role, used_ids),
                role=role,
                label=_first_text(plan.get("content_anchor"), plan.get("visual_archetype"), role.title()),
                douyin_keyword=douyin_keyword,
                pinterest_keyword=pinterest_keyword,
                douyin_fallback=_first_text(*_fallbacks_for_source(plan, "douyin")),
                pinterest_fallback=_first_text(*_fallbacks_for_source(plan, "pinterest")),
                scene_ids=[],
            )
            grouped[key] = group
            groups.append(group)
        group.scene_ids.append(scene.scene_id)
    return MaterialSearchPlan(popular_first=project.material_search_plan.popular_first, groups=groups)


def _fallback_material_search_plan(project: VideoDesignProject, scenes: list[ScenePlan]) -> MaterialSearchPlan:
    scene_ids = [scene.scene_id for scene in scenes]
    return MaterialSearchPlan(
        popular_first=project.material_search_plan.popular_first,
        groups=[_fallback_material_search_group(project, scenes, scene_ids)],
    )


def _fallback_material_search_group(
    project: VideoDesignProject,
    scenes: list[ScenePlan],
    scene_ids: list[str],
) -> MaterialSearchGroup:
    keyword = _project_base_keyword(project, scenes)
    return MaterialSearchGroup(
        group_id="grp_base",
        role="base",
        label=keyword or "Base",
        douyin_keyword=keyword,
        pinterest_keyword=keyword,
        scene_ids=list(scene_ids),
    )


def _project_base_keyword(project: VideoDesignProject, scenes: list[ScenePlan] | None = None) -> str:
    scene_list = scenes or project.scenes
    candidates = [project.idea]
    if scene_list:
        candidates.extend(
            [
                scene_list[0].matching_keywords[0] if scene_list[0].matching_keywords else "",
                scene_list[0].visual_brief,
                scene_list[0].voiceover_text,
            ]
        )
    candidates.append(project.script)
    for candidate in candidates:
        phrase = _keyword_phrase(candidate)
        words = phrase.split()
        if words:
            return " ".join(words[:2])
    return "daily life"


def _unique_search_group_id(role: str, label: str, used_ids: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(label or "").lower()).strip("_")[:36]
    base = f"grp_{slug or role}"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _merge_generated_material_search_plan(
    project: VideoDesignProject,
    scenes: list[ScenePlan],
    generated: MaterialSearchPlan,
) -> MaterialSearchPlan:
    selected_ids = {scene.scene_id for scene in scenes}
    all_scene_ids = {scene.scene_id for scene in project.scenes}
    if selected_ids == all_scene_ids or not project.material_search_plan.groups:
        return _normalize_user_material_search_plan(project, generated)

    preserved = []
    for group in project.material_search_plan.groups:
        remaining = [scene_id for scene_id in group.scene_ids if scene_id not in selected_ids]
        if remaining:
            preserved.append(group.model_copy(update={"scene_ids": remaining}))
    combined = MaterialSearchPlan(
        popular_first=project.material_search_plan.popular_first,
        groups=[*generated.groups, *preserved],
    )
    return _normalize_user_material_search_plan(project, combined)


def _normalize_user_material_search_plan(project: VideoDesignProject, plan: MaterialSearchPlan) -> MaterialSearchPlan:
    return _normalize_user_material_search_plan_for_scenes(
        project,
        plan,
        {scene.scene_id for scene in project.scenes},
    )


def _normalize_user_material_search_plan_for_scenes(
    project: VideoDesignProject,
    plan: MaterialSearchPlan,
    valid_scene_ids: set[str],
) -> MaterialSearchPlan:
    used_ids: set[str] = set()
    assigned: set[str] = set()
    normalized: list[MaterialSearchGroup] = []
    coalesced: dict[tuple[str, str], MaterialSearchGroup] = {}

    for item in plan.groups:
        role = item.role if item.role in {"hook", "base", "exact"} else "base"
        exact_subject = _first_text(item.exact_subject) if role == "exact" else ""
        key_subject = exact_subject.lower() if role == "exact" else role
        key = (role, key_subject)
        scene_ids = []
        for scene_id in item.scene_ids:
            if scene_id not in valid_scene_ids or scene_id in assigned:
                continue
            scene_ids.append(scene_id)
            assigned.add(scene_id)
        if not scene_ids:
            continue

        existing = coalesced.get(key)
        if existing:
            existing.scene_ids.extend(scene_ids)
            continue

        requested_id = re.sub(r"[^A-Za-z0-9_-]+", "_", item.group_id or "").strip("_")
        group_id = requested_id if requested_id and requested_id not in used_ids else _unique_search_group_id(role, exact_subject or item.label, used_ids)
        used_ids.add(group_id)
        base_keyword = _project_base_keyword(project)
        douyin_keyword = _first_text(*_normalize_keywords([item.douyin_keyword], 1), base_keyword)
        pinterest_keyword = _first_text(*_normalize_keywords([item.pinterest_keyword], 1), base_keyword)
        group = MaterialSearchGroup(
            group_id=group_id,
            role=role,
            label=_first_text(item.label, exact_subject, pinterest_keyword, role.title()),
            exact_subject=exact_subject,
            douyin_keyword=douyin_keyword,
            pinterest_keyword=pinterest_keyword,
            douyin_fallback=_first_text(*_normalize_keywords([item.douyin_fallback], 1)),
            pinterest_fallback=_first_text(*_normalize_keywords([item.pinterest_fallback], 1)),
            scene_ids=scene_ids,
        )
        normalized.append(group)
        coalesced[key] = group

    missing = [scene.scene_id for scene in project.scenes if scene.scene_id in valid_scene_ids and scene.scene_id not in assigned]
    if missing:
        base = next((group for group in normalized if group.role == "base"), None)
        if not base:
            base = _fallback_material_search_group(project, project.scenes, [])
            if base.group_id in used_ids:
                base.group_id = _unique_search_group_id("base", "base", used_ids)
            normalized.append(base)
        base.scene_ids.extend(missing)

    if normalized and not any(group.role == "base" for group in normalized):
        source_group = next((group for group in reversed(normalized) if group.scene_ids), None)
        if source_group:
            base_scene_id = source_group.scene_ids.pop()
            normalized = [group for group in normalized if group.scene_ids]
            base = _fallback_material_search_group(project, project.scenes, [base_scene_id])
            if base.group_id in used_ids:
                base.group_id = _unique_search_group_id("base", "base", used_ids)
            normalized.append(base)

    return MaterialSearchPlan(popular_first=bool(plan.popular_first), groups=normalized)


def _sync_scenes_from_material_search_plan(
    project: VideoDesignProject,
    query_strategy: str = "shared_pool_v3",
) -> None:
    groups = {scene_id: group for group in project.material_search_plan.groups for scene_id in group.scene_ids}
    for scene in project.scenes:
        group = groups.get(scene.scene_id)
        if not group:
            continue
        scene.search_group_id = group.group_id
        scene.visual_search_plan = {
            "search_group_id": group.group_id,
            "search_role": group.role,
            "exact_subject": group.exact_subject,
            "retention_role": "hook" if group.role == "hook" else "evidence",
            "content_anchor": group.exact_subject or group.label,
            "visible_action": "",
            "visual_intent": group.label,
            "visual_archetype": group.label,
            "douyin_primary_keyword": group.douyin_keyword,
            "pinterest_primary_keyword": group.pinterest_keyword,
            "fallbacks": {
                "douyin": [group.douyin_fallback] if group.douyin_fallback else [],
                "pinterest": [group.pinterest_fallback] if group.pinterest_fallback else [],
            },
            "avoid": [],
            "material_notes": f"Shared {group.role} search group: {group.label}.",
            "query_strategy": query_strategy,
        }
        scene.matching_keywords = _normalize_keywords([group.pinterest_keyword, group.douyin_keyword], 1)


def _sync_scene_group_ids(project: VideoDesignProject, preserve_visual_plans: bool = False) -> None:
    groups = {scene_id: group for group in project.material_search_plan.groups for scene_id in group.scene_ids}
    for scene in project.scenes:
        group = groups.get(scene.scene_id)
        if not group:
            continue
        scene.search_group_id = group.group_id
        if preserve_visual_plans:
            scene.visual_search_plan = {
                **scene.visual_search_plan,
                "search_group_id": group.group_id,
                "search_role": group.role,
                "exact_subject": group.exact_subject,
            }


def _normalize_visual_search_plan(data: dict, project: VideoDesignProject, scene: ScenePlan) -> dict:
    item = next(
        (
            candidate
            for candidate in data.get("scenes") or []
            if str(candidate.get("scene_id") or "") == scene.scene_id
        ),
        {},
    )
    if not item:
        return {}

    global_hook = data.get("global_hook_strategy") or {}
    is_hook = scene.order == 1
    douyin_primary = _normalize_douyin_visual_query(
        _first_text(
            item.get("douyin_primary_keyword"),
            global_hook.get("douyin_primary_keyword") if is_hook else "",
        )
    )
    pinterest_primary = _normalize_pinterest_visual_query(
        _first_text(
            item.get("pinterest_primary_keyword"),
            global_hook.get("pinterest_primary_keyword") if is_hook else "",
        )
    )
    fallback = _fallback_visual_search_plan_from_keywords(
        scene,
        _normalize_keywords(
            [douyin_primary, pinterest_primary, *(_fallbacks_for_source(item, "douyin")), *(_fallbacks_for_source(item, "pinterest"))],
            3,
        ),
    )
    if not douyin_primary:
        douyin_primary = fallback["douyin_primary_keyword"]
    if not pinterest_primary:
        pinterest_primary = fallback["pinterest_primary_keyword"]
    if not douyin_primary and not pinterest_primary:
        return {}

    content_anchor = _first_text(item.get("content_anchor"), data.get("project_anchor"))
    if not _visual_plan_is_grounded(project, scene, content_anchor, pinterest_primary):
        fallback = _fallback_visual_search_plan(project, scene)
        fallback.update(
            {
                "content_anchor": content_anchor,
                "visible_action": _first_text(item.get("visible_action")),
                "query_strategy": "fallback_ungrounded",
                "material_notes": "Rejected an ungrounded or off-topic model query; using a broad local fallback.",
            }
        )
        return fallback

    return {
        "project_anchor": _first_text(data.get("project_anchor")),
        "retention_role": _first_text(item.get("retention_role"), "hook" if is_hook else "evidence"),
        "content_anchor": content_anchor,
        "visible_action": _first_text(item.get("visible_action")),
        "visual_intent": _first_text(item.get("visual_intent"), scene.visual_brief, scene.voiceover_text),
        "visual_archetype": _first_text(item.get("visual_archetype"), scene.visual_brief),
        "douyin_primary_keyword": douyin_primary,
        "pinterest_primary_keyword": pinterest_primary,
        "fallbacks": {
            "douyin": _normalize_keywords(
                [_normalize_douyin_visual_query(value) for value in _fallbacks_for_source(item, "douyin")],
                2,
            ),
            "pinterest": _normalize_keywords(
                [_normalize_pinterest_visual_query(value) for value in _fallbacks_for_source(item, "pinterest")],
                2,
            ),
        },
        "avoid": _normalize_keywords(item.get("avoid", []), 8),
        "material_notes": _first_text(item.get("material_notes"), ""),
        "query_strategy": "broad_grounded_v2",
    }


def _fallback_visual_search_plan(project: VideoDesignProject, scene: ScenePlan) -> dict:
    return _fallback_visual_search_plan_from_keywords(scene, _fallback_keywords_for_scene(project, scene, 3))


def _fallback_visual_search_plan_from_keywords(scene: ScenePlan, keywords: list[str]) -> dict:
    normalized = _normalize_keywords(keywords, 3)
    primary = normalized[0] if normalized else "raw vertical footage"
    fallbacks = normalized[1:3]
    return {
        "retention_role": "hook" if scene.order == 1 else "evidence",
        "content_anchor": _keyword_phrase(scene.visual_brief or scene.voiceover_text),
        "visible_action": "",
        "visual_intent": scene.visual_brief or scene.voiceover_text,
        "visual_archetype": scene.visual_brief or "",
        "douyin_primary_keyword": primary,
        "pinterest_primary_keyword": primary,
        "fallbacks": {"douyin": fallbacks, "pinterest": fallbacks},
        "avoid": _normalize_keywords(scene.negative_keywords, 8),
        "material_notes": "Fallback keyword generated without DeepSeek visual search plan.",
        "query_strategy": "fallback_local",
    }


def _normalize_douyin_visual_query(query: str) -> str:
    value = re.sub(r"\s+", " ", str(query or "")).strip(" ,.;:-")
    for source, replacement in DOUYIN_QUERY_REPLACEMENTS.items():
        value = value.replace(source, replacement)
    for term in DOUYIN_QUERY_DROP_TERMS:
        value = value.replace(term, " ")
    if re.search(r"[\u3040-\u30ff]", value):
        return ""
    return " ".join(value.split()[:4])[:48].strip()


def _normalize_pinterest_visual_query(query: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", str(query or ""))
    filtered = [word for word in words if word.lower() not in PINTEREST_QUERY_DROP_WORDS]
    if len(filtered) <= 6:
        return " ".join(filtered)
    has_video = any(word.lower() == "video" for word in filtered)
    content = [word for word in filtered if word.lower() != "video"][: 5 if has_video else 6]
    if has_video:
        content.append("video")
    return " ".join(content)


def _visual_plan_is_grounded(
    project: VideoDesignProject,
    scene: ScenePlan,
    content_anchor: str,
    pinterest_query: str,
) -> bool:
    anchor_tokens = _visual_grounding_tokens(content_anchor)
    if not anchor_tokens:
        return False
    context_tokens = _visual_grounding_tokens(
        " ".join(
            [
                project.idea,
                project.script,
                scene.voiceover_text,
                scene.on_screen_text,
                scene.visual_brief,
            ]
        )
    )
    query_tokens = _visual_grounding_tokens(pinterest_query)
    return bool(anchor_tokens & context_tokens) and bool(anchor_tokens & query_tokens)


def _visual_grounding_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z'-]*", text or ""):
        value = raw.lower().strip("'-")
        value = VISUAL_TOKEN_ALIASES.get(value, value)
        if value.endswith("ies") and len(value) > 4:
            value = f"{value[:-3]}y"
        elif value.endswith("s") and len(value) > 4 and not value.endswith(("ss", "us", "is")):
            value = value[:-1]
        value = VISUAL_TOKEN_ALIASES.get(value, value)
        if len(value) < 3 or value in KEYWORD_STOPWORDS or value in VISUAL_QUERY_GENERIC_TOKENS:
            continue
        tokens.add(value)
    return tokens


def _ensure_material_search_plan(project: VideoDesignProject, scenes: list[ScenePlan]) -> None:
    if project.material_search_plan.groups:
        _sync_scene_group_ids(project, preserve_visual_plans=True)
        return
    source_scenes = project.scenes or scenes
    project.material_search_plan = _normalize_user_material_search_plan(
        project,
        _material_search_plan_from_scene_plans(project, source_scenes),
    )
    _sync_scene_group_ids(project, preserve_visual_plans=True)


def _search_groups_for_request(
    project: VideoDesignProject,
    request: MaterialsSearchRequest,
) -> list[MaterialSearchGroup]:
    groups = project.material_search_plan.groups
    if request.group_ids:
        requested = set(request.group_ids)
        selected = [group for group in groups if group.group_id in requested]
        if len(selected) != len(requested):
            raise VideoDesignError(INVALID_PROJECT_INPUT, "One or more material search groups do not exist.")
        return selected
    if request.scene_ids:
        requested_scenes = set(request.scene_ids)
        selected = [group for group in groups if requested_scenes.intersection(group.scene_ids)]
        if not selected:
            raise VideoDesignError(INVALID_PROJECT_INPUT, "Selected scenes do not have a material search group.")
        return selected
    return groups


def _keywords_for_search_group(group: MaterialSearchGroup, source: str, limit: int) -> list[str]:
    if source == "douyinsearch":
        values = [group.douyin_keyword, group.douyin_fallback]
    else:
        values = [group.pinterest_keyword, group.pinterest_fallback]
    return _normalize_keywords(values, limit)


def _legacy_keywords_from_visual_plan(plan: dict, limit: int) -> list[str]:
    return _normalize_keywords([plan.get("pinterest_primary_keyword"), plan.get("douyin_primary_keyword")], limit)


def _fallbacks_for_source(plan: dict, source_key: str) -> list[str]:
    fallbacks = plan.get("fallbacks") or {}
    values = fallbacks.get(source_key) or []
    if isinstance(values, str):
        values = [values]
    return [str(value).strip() for value in values if str(value).strip()]


def _first_text(*values) -> str:
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            return text[:240]
    return ""


def _should_translate_douyin_keyword(keyword: str, requested: bool) -> bool:
    return bool(requested and not re.search(r"[\u3400-\u9fff]", keyword or ""))


def _keyword_phrase(text: str | None) -> str:
    words = []
    for word in re.findall(r"[A-Za-z0-9]+", text or ""):
        value = word.lower()
        if len(value) < 3 or value in KEYWORD_STOPWORDS or value in words:
            continue
        words.append(value)
        if len(words) >= 4:
            break
    return " ".join(words)


def _append_keyword(keywords: list[str], keyword: str) -> None:
    if keyword and keyword.lower() not in {item.lower() for item in keywords}:
        keywords.append(keyword)
