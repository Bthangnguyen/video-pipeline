from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SplitMode = Literal["auto", "dense", "normal", "sparse", "manual"]
ApprovalState = Literal["planned", "searching", "needs_review", "approved", "download_pending", "downloaded", "rejected", "placeholder_allowed"]
CandidateStatus = Literal["proposed", "approved", "rejected"]
SFXSuggestionStatus = Literal["proposed", "applied", "skipped"]


class SplitSettings(BaseModel):
    split_mode: SplitMode = "normal"
    target_scene_duration_seconds: float = Field(default=4, ge=1)
    min_scene_duration_seconds: float = Field(default=2.5, ge=1)
    max_scene_duration_seconds: float = Field(default=7, ge=1)
    max_words_per_scene: int = Field(default=18, ge=4, le=80)
    allow_manual_boundaries: bool = True


class TTSSettings(BaseModel):
    language: str = "en"
    provider: str = "free_tts"
    voice_id: str = "en-US-AriaNeural"


class CaptionChunk(BaseModel):
    text: str
    start: float
    end: float


class SceneAudioOffset(BaseModel):
    scene_id: str
    start_seconds: float
    end_seconds: float


class TTSMeta(BaseModel):
    provider: str = ""
    voice_id: str = ""
    audio_url: str = ""
    audio_path: str = ""
    duration_seconds: float = 0
    sync_state: str = "pending"


class SceneClip(BaseModel):
    material_asset_id: str
    trim_source: str = "auto_start"
    trim_start_seconds: float = 0
    trim_end_seconds: float = 0
    duration_seconds: float = 0
    fit: str = "cover"
    loop_mode: str = "none"
    status: str = "trim_auto"
    transform: dict[str, Any] = Field(
        default_factory=lambda: {
            "flip_horizontal": False,
            "crop_x": 50,
            "crop_y": 50,
            "zoom": 1,
            "rotation": 0,
        }
    )
    effects: dict[str, Any] = Field(
        default_factory=lambda: {
            "brightness": 1,
            "contrast": 1,
            "saturation": 1,
            "sharpness": 0,
        }
    )
    transition: dict[str, Any] = Field(default_factory=dict)


class ScenePlan(BaseModel):
    scene_id: str
    order: int
    voiceover_text: str
    tts_text: str = ""
    on_screen_text: str = ""
    caption_text: str = ""
    caption_chunks: list[CaptionChunk] = Field(default_factory=list)
    visual_brief: str = ""
    matching_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    template_scene_id: str = ""
    duration_seconds: float = 0
    search_tasks: list[str] = Field(default_factory=list)
    tts: TTSMeta = Field(default_factory=TTSMeta)
    approval_state: ApprovalState = "planned"
    selected_candidate_id: str | None = None
    material_asset_id: str | None = None
    clip: SceneClip | None = None


class DouyinSearchTask(BaseModel):
    search_task_id: str
    project_id: str
    scene_id: str
    source: str = "douyinsearch"
    keyword: str
    translate_to_chinese: bool = True
    limit: int = 12
    status: str = "planned"
    douyin_query_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class MediaCandidate(BaseModel):
    candidate_id: str
    source: str = "douyinsearch"
    scene_id: str
    source_result_id: str = ""
    source_item_id: str = ""
    source_url: str = ""
    search_keyword: str = ""
    douyin_result_id: str = ""
    douyin_aweme_id: str = ""
    title: str = ""
    cover_url: str = ""
    stream_url: str = ""
    media_url: str = ""
    download_url: str = ""
    remote_stream_url: str = ""
    remote_download_url: str = ""
    duration: float = 0
    match_reason: str = ""
    status: CandidateStatus = "proposed"


class MaterialAsset(BaseModel):
    asset_id: str
    project_id: str
    scene_id: str
    candidate_id: str
    source: str = "douyinsearch"
    source_result_id: str = ""
    source_item_id: str = ""
    source_url: str = ""
    search_keyword: str = ""
    douyin_result_id: str = ""
    douyin_aweme_id: str = ""
    local_path: str
    proxy_path: str = ""
    media_type: str = "video/mp4"
    duration: float = 0
    download_state: str = "downloaded"


class SFXAsset(BaseModel):
    asset_id: str
    name: str
    category: str
    audio_url: str
    local_path: str
    duration_seconds: float
    default_volume: float = 0.35
    recommended_events: list[str] = Field(default_factory=list)


class SFXSuggestion(BaseModel):
    suggestion_id: str
    event_id: str
    project_id: str
    scene_id: str = ""
    event_type: str
    time_seconds: float
    duration_hint_seconds: float
    label: str
    reason: str
    asset_id: str
    volume: float = 0.35
    status: SFXSuggestionStatus = "proposed"


class TimelineItem(BaseModel):
    item_id: str
    layer_id: str
    scene_id: str
    type: str
    start_seconds: float
    end_seconds: float
    source_ref: dict[str, Any] = Field(default_factory=dict)
    transform: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)


class TimelineDraft(BaseModel):
    timeline_id: str
    project_id: str
    duration_seconds: float
    aspect_ratio: str
    scenes: list[str] = Field(default_factory=list)
    layers: list[str] = Field(default_factory=list)
    items: list[TimelineItem] = Field(default_factory=list)


class SmoothPreview(BaseModel):
    status: Literal["missing", "rendering", "ready", "stale", "failed"] = "missing"
    preview_url: str = ""
    preview_path: str = ""
    timeline_id: str = ""
    duration_seconds: float = 0
    updated_at: str = ""
    error: dict[str, Any] = Field(default_factory=dict)


class ProjectProgress(BaseModel):
    stage: str = "idle"
    message: str = ""
    current: int = 0
    total: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)


class VoiceoverTrack(BaseModel):
    audio_url: str = ""
    audio_path: str = ""
    duration_seconds: float = 0
    scene_offsets: list[SceneAudioOffset] = Field(default_factory=list)


class VideoDesignProject(BaseModel):
    project_id: str
    status: str = "draft"
    idea: str = ""
    script_source: str = "user"
    script: str = ""
    target_platform: str = "tiktok"
    aspect_ratio: str = "9:16"
    target_duration_seconds: float = 45
    language: str = "en"
    style_brief: str = ""
    design_preset: dict[str, Any] = Field(default_factory=dict)
    split_settings: SplitSettings = Field(default_factory=SplitSettings)
    tts_settings: TTSSettings = Field(default_factory=TTSSettings)
    scenes: list[ScenePlan] = Field(default_factory=list)
    search_tasks: list[DouyinSearchTask] = Field(default_factory=list)
    candidates: list[MediaCandidate] = Field(default_factory=list)
    material_assets: list[MaterialAsset] = Field(default_factory=list)
    sfx_suggestions: list[SFXSuggestion] = Field(default_factory=list)
    timeline: TimelineDraft | None = None
    smooth_preview: SmoothPreview = Field(default_factory=SmoothPreview)
    voiceover_track: VoiceoverTrack = Field(default_factory=VoiceoverTrack)
    progress: ProjectProgress = Field(default_factory=ProjectProgress)
    created_at: str


class CreateProjectRequest(BaseModel):
    idea: str | None = None
    script: str | None = None
    target_platform: str = "tiktok"
    aspect_ratio: str = "9:16"
    target_duration_seconds: float = Field(default=45, ge=5)
    language: str = "en"
    style_brief: str = ""

    @model_validator(mode="after")
    def require_idea_or_script(self):
        if not (self.idea or "").strip() and not (self.script or "").strip():
            raise ValueError("Either idea or script is required.")
        return self


class ScriptGenerateRequest(BaseModel):
    idea: str | None = None
    target_duration_seconds: float | None = None
    tone: str = ""
    language: str = "en"


class TTSGenerateRequest(BaseModel):
    scene_ids: list[str] | None = None
    provider: str | None = None
    voice_id: str | None = None


class KeywordGenerateRequest(BaseModel):
    scene_ids: list[str] | None = None


class MaterialsSearchRequest(BaseModel):
    scene_ids: list[str] | None = None
    candidates_per_scene: int = Field(default=5, ge=1, le=10)
    douyin_min_per_scene: int | None = Field(default=None, ge=0, le=10)
    pinterest_min_per_scene: int = Field(default=0, ge=0, le=10)
    queries_per_scene: int = Field(default=2, ge=1, le=3)
    translate_to_chinese: bool = True
    use_smart_keywords: bool = False


class MaterialsPreflightRequest(BaseModel):
    keyword: str = "cat"


class SceneSelectionRequest(BaseModel):
    action: Literal["approve", "reject", "manual_select", "placeholder"]
    candidate_id: str | None = None
    douyin_result_id: str | None = None


class MaterialsDownloadRequest(BaseModel):
    scene_ids: list[str] | None = None
    force: bool = False


class MaterialsPruneRequest(BaseModel):
    scene_ids: list[str] | None = None


class SceneClipPatch(BaseModel):
    material_asset_id: str | None = None
    trim_source: Literal["manual", "auto_start"] = "manual"
    trim_start_seconds: float = Field(default=0, ge=0)
    asset_duration_seconds: float | None = Field(default=None, ge=0)
    loop_mode: str | None = None
    transform: dict[str, Any] | None = None
    effects: dict[str, Any] | None = None
    transition: dict[str, Any] | None = None


class TimelineItemPatch(BaseModel):
    start_seconds: float | None = None
    end_seconds: float | None = None
    source_ref: dict[str, Any] | None = None
    transform: dict[str, Any] | None = None
    style: dict[str, Any] | None = None


class TimelineItemCreateRequest(BaseModel):
    scene_id: str
    type: Literal["text", "caption", "overlay", "icon", "transition", "music", "sfx"]
    layer_id: str | None = None
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    transform: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)


class TransitionRequest(BaseModel):
    transition_id: str = "fade"
    duration_seconds: float = Field(default=0.35, ge=0.05, le=1.5)


class SFXSuggestRequest(BaseModel):
    max_suggestions: int = Field(default=12, ge=1, le=40)
    include_caption_words: bool = True
    include_transitions: bool = True
    include_icons: bool = True
    include_text: bool = True
    include_hook: bool = True


class SFXApplyRequest(BaseModel):
    suggestion_ids: list[str] | None = None
