import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.douyinsearch.config import settings as douyin_settings
from app.douyinsearch.cookies import cookie_header_from_file as douyin_cookie_header_from_file
from app.douyinsearch.stream_proxy import no_watermark_url_from_result
from app.douyinsearch.service import douyin_service
from app.pinterestsearch.config import settings as pinterest_settings
from app.pinterestsearch.cookies import cookie_header_from_file as pinterest_cookie_header_from_file
from app.videodesign.config import settings
from app.videodesign.errors import CANDIDATE_NOT_FOUND, DOWNLOAD_FAILED, VideoDesignError
from app.videodesign.materials.search_plan import _first_text
from app.videodesign.schemas import MaterialAsset, MaterialSearchGroup, MediaCandidate, ScenePlan, VideoDesignProject


def _candidate(project: VideoDesignProject, candidate_id: str | None) -> MediaCandidate:
    for candidate in project.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    raise VideoDesignError(CANDIDATE_NOT_FOUND, "Candidate does not exist.")


def _approved_candidate_for_scene(project: VideoDesignProject, scene: ScenePlan) -> MediaCandidate | None:
    if not scene.selected_candidate_id:
        return None
    try:
        candidate = _candidate(project, scene.selected_candidate_id)
    except VideoDesignError:
        return None
    if candidate.scene_id != scene.scene_id or candidate.status != "approved":
        return None
    return candidate


def _asset(project: VideoDesignProject, asset_id: str) -> MaterialAsset:
    for asset in project.material_assets:
        if asset.asset_id == asset_id:
            return asset
    raise VideoDesignError(DOWNLOAD_FAILED, "Material asset does not exist.")


def _material_output_path(project: VideoDesignProject, scene: ScenePlan) -> Path:
    return settings.storage_dir / project.project_id / "materials" / f"{scene.scene_id}.mp4"


def _material_asset_from_candidate(
    project: VideoDesignProject,
    scene: ScenePlan,
    candidate: MediaCandidate,
    output_path: Path,
) -> MaterialAsset:
    return MaterialAsset(
        asset_id=f"mat_{uuid.uuid4().hex}",
        project_id=project.project_id,
        scene_id=scene.scene_id,
        candidate_id=candidate.candidate_id,
        source=candidate.source,
        source_result_id=candidate.source_result_id,
        source_item_id=candidate.source_item_id,
        source_url=candidate.source_url,
        search_keyword=candidate.search_keyword,
        douyin_result_id=candidate.douyin_result_id,
        douyin_aweme_id=candidate.douyin_aweme_id,
        local_path=str(output_path),
        duration=candidate.duration,
    )


def _recover_candidate_for_existing_material(
    project: VideoDesignProject,
    scene: ScenePlan,
    output_path: Path,
) -> MediaCandidate | None:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return None
    if scene.selected_candidate_id:
        try:
            candidate = _candidate(project, scene.selected_candidate_id)
            candidate.status = "approved"
            return candidate
        except VideoDesignError:
            pass
    candidate = MediaCandidate(
        candidate_id=f"cand_recovered_{uuid.uuid4().hex}",
        source="recovered",
        scene_id=scene.scene_id,
        title=f"Recovered local material for scene {scene.order}",
        search_keyword=", ".join(scene.matching_keywords),
        status="approved",
    )
    project.candidates.append(candidate)
    scene.selected_candidate_id = candidate.candidate_id
    return candidate


def _recover_existing_material_asset(
    project: VideoDesignProject,
    scene: ScenePlan,
    candidate: MediaCandidate,
    output_path: Path,
) -> MaterialAsset | None:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return None
    existing = next(
        (
            asset
            for asset in project.material_assets
            if asset.scene_id == scene.scene_id and Path(asset.local_path) == output_path
        ),
        None,
    )
    asset = existing or _material_asset_from_candidate(project, scene, candidate, output_path)
    if not existing:
        project.material_assets.append(asset)
    scene.material_asset_id = asset.asset_id
    scene.clip = None
    scene.approval_state = "downloaded"
    return asset


def _candidates_for_scene(project: VideoDesignProject, scene_id: str, source: str | None = None) -> list[MediaCandidate]:
    return [
        candidate
        for candidate in project.candidates
        if candidate.scene_id == scene_id
        and candidate.status != "rejected"
        and (source is None or candidate.source == source)
    ]


def _add_group_candidates(
    project: VideoDesignProject,
    group: MaterialSearchGroup,
    scenes: list[ScenePlan],
    results,
    limit_per_scene: int,
    source: str,
    keyword: str,
    diagnostics: dict,
    popular_first: bool,
) -> list[str]:
    candidate_ids: list[str] = []
    popularity = _candidate_popularity(source, popular_first, diagnostics)
    for scene in scenes:
        needed = max(0, limit_per_scene - len(_candidates_for_scene(project, scene.scene_id, source)))
        if needed <= 0:
            continue
        candidate_ids.extend(
            _add_candidates(
                project,
                scene,
                results,
                needed,
                source,
                keyword,
                search_group_id=group.group_id,
                popularity=popularity,
            )
        )
    return candidate_ids


def _candidate_popularity(source: str, requested: bool, diagnostics: dict | None) -> dict:
    if source == "pinterestsearch":
        return {
            "requested": bool(requested),
            "applied": False,
            "method": "platform_order",
            "publish_window_days": 0,
        }
    detail = (diagnostics or {}).get("popularity") or {}
    return {
        "requested": bool(requested),
        "applied": bool(detail.get("applied", False)) if requested else False,
        "method": _first_text(detail.get("method"), "relevance" if not requested else "popular_unavailable"),
        "publish_window_days": int(detail.get("publish_window_days") or (180 if requested else 0)),
    }


def _add_candidates(
    project: VideoDesignProject,
    scene: ScenePlan,
    results,
    limit: int,
    source: str,
    keyword: str,
    search_group_id: str = "",
    popularity: dict | None = None,
) -> list[str]:
    existing = {
        (candidate.source, candidate.source_result_id or candidate.douyin_result_id)
        for candidate in project.candidates
        if candidate.scene_id == scene.scene_id
    }
    candidate_ids = []
    for source_rank, result in enumerate(results, start=1):
        if (source, result.result_id) in existing:
            continue
        candidate = _candidate_from_public_result(
            scene,
            result,
            source_rank,
            source,
            keyword,
            search_group_id=search_group_id,
            popularity=popularity,
        )
        project.candidates.append(candidate)
        candidate_ids.append(candidate.candidate_id)
        if len(candidate_ids) >= limit:
            break
    return candidate_ids


def _candidate_from_public_result(
    scene: ScenePlan,
    result,
    index: int,
    source: str = "douyinsearch",
    keyword: str = "",
    search_group_id: str = "",
    popularity: dict | None = None,
) -> MediaCandidate:
    source_item_id = str(getattr(result, "douyin_aweme_id", "") or getattr(result, "pin_id", "") or "")
    title = result.title or result.description or source_item_id
    duration = float(getattr(result, "duration", 0) or 0)
    douyin_aweme_id = source_item_id if source == "douyinsearch" else ""
    remote_stream_url = ""
    remote_download_url = ""
    if source == "douyinsearch":
        stored_result = douyin_service.store.get(result.result_id)
        if stored_result:
            remote_stream_url = stored_result.stream_remote_url
            remote_download_url = no_watermark_url_from_result(stored_result)
    return MediaCandidate(
        candidate_id=f"cand_{uuid.uuid4().hex}",
        source=source,
        scene_id=scene.scene_id,
        search_group_id=search_group_id or scene.search_group_id,
        source_result_id=result.result_id,
        source_item_id=source_item_id,
        source_url=str(getattr(result, "source_url", "") or ""),
        search_keyword=keyword,
        douyin_result_id=result.result_id if source == "douyinsearch" else "",
        douyin_aweme_id=douyin_aweme_id,
        title=title,
        cover_url=result.cover_url,
        stream_url=result.stream_url,
        media_url=str(getattr(result, "media_url", "") or ""),
        download_url=result.download_url,
        remote_stream_url=remote_stream_url,
        remote_download_url=remote_download_url,
        duration=duration,
        source_rank=index,
        stats=dict(getattr(result, "stats", {}) or {}),
        popularity=dict(popularity or {}),
        match_reason=f"{source_label(source)} result {index} from the shared search pool.",
    )


def _search_errors_for_scene(project: VideoDesignProject, scene_id: str) -> list[dict]:
    errors = []
    scene = next((item for item in project.scenes if item.scene_id == scene_id), None)
    search_group_id = scene.search_group_id if scene else ""
    for task in project.search_tasks:
        belongs_to_scene = task.scene_id == scene_id or (search_group_id and task.search_group_id == search_group_id)
        if not belongs_to_scene or not task.error:
            continue
        errors.append(
            {
                "source": task.source,
                "keyword": task.keyword,
                "search_group_id": task.search_group_id,
                "code": task.error.get("code", "MATERIAL_SEARCH_FAILED"),
                "message": task.error.get("message", ""),
                "retryable": bool(task.error.get("retryable", False)),
            }
        )
    return errors


def _download_source_url(candidate: MediaCandidate) -> str:
    if _is_http_url(candidate.source_url):
        return candidate.source_url
    if candidate.source == "pinterestsearch" and candidate.source_item_id:
        return f"https://www.pinterest.com/pin/{candidate.source_item_id}/"
    aweme_id = candidate.douyin_aweme_id or candidate.source_item_id
    if candidate.source == "douyinsearch" and aweme_id:
        return f"https://www.douyin.com/video/{aweme_id}"
    return ""


def _cookie_file_for_source(source: str) -> Path | None:
    if source == "pinterestsearch":
        return pinterest_settings.cookie_file
    if source == "douyinsearch":
        return douyin_settings.cookie_file
    return None


def _cookie_header_for_source(source: str) -> str:
    cookie_file = _cookie_file_for_source(source)
    if not cookie_file or not cookie_file.exists():
        return ""
    if source == "pinterestsearch":
        return pinterest_cookie_header_from_file(cookie_file)
    if source == "douyinsearch":
        return douyin_cookie_header_from_file(cookie_file)
    return ""


def _is_blob_url(url: str) -> bool:
    return str(url or "").lower().startswith("blob:")


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def source_label(source: str) -> str:
    return {
        "douyinsearch": "Douyin",
        "pinterestsearch": "Pinterest",
    }.get(source, source)
