from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

MANUSCRIPT_STATUS_VALUES = Literal[
    "Working Draft",
    "Internal Review",
    "Ready for Submission",
    "Submitted",
    "Under Review",
    "Revision Requested",
    "Accepted",
    "Published",
    "Rejected",
    "Archived",
]
# Statuses that describe the paper's external publication state are owner-controlled,
# matching the existing rule that owners control authoritative publication status.
OWNER_ONLY_MANUSCRIPT_STATUSES = {"Submitted", "Under Review", "Revision Requested", "Accepted", "Published", "Rejected"}

# TeX engine the source is written for; only used to tailor the export README.
ENGINE_VALUES = Literal["pdflatex", "xelatex", "lualatex"]


class ManuscriptCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    template: Literal["blank", "article", "ieee", "structured"] = "article"
    compiler: ENGINE_VALUES = "pdflatex"


class ManuscriptUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    main_file_path: Optional[str] = Field(default=None, max_length=400)
    compiler: Optional[ENGINE_VALUES] = None
    review_status: Optional[Literal["draft", "in_review", "approved", "changes_requested"]] = None
    is_pinned: Optional[bool] = None
    linked_artifacts: Optional[List[Dict[str, str]]] = Field(default=None, max_length=200)


class ManuscriptStatusRequest(BaseModel):
    status: MANUSCRIPT_STATUS_VALUES


class ManuscriptCopyRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)


class ManuscriptFileCreateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=400)
    kind: Literal["text", "folder"] = "text"
    content: str = Field(default="", max_length=4_000_000)


class ManuscriptFileUpdateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=400)


class VersionCreateRequest(BaseModel):
    summary: str = Field(default="Saved version", max_length=300)


class FileContentSaveRequest(BaseModel):
    content: str = Field(..., max_length=4_000_000)
    base_revision: int = Field(..., ge=1, description="Revision the edit started from; a newer saved revision causes 409")


class CommentAnchor(BaseModel):
    """Where a comment points: character offsets plus the quoted text and its surroundings,
    which let the client re-find the passage after later edits."""

    from_offset: int = Field(default=0, ge=0, alias="from")
    to_offset: int = Field(default=0, ge=0, alias="to")
    line: int = Field(default=0, ge=0)
    context_before: str = Field(default="", max_length=200)
    context_after: str = Field(default="", max_length=200)
    target: Literal["range", "document", "figure", "table", "section", "equation"] = "range"
    target_label: str = Field(default="", max_length=200)

    model_config = {"populate_by_name": True}


class DocCommentCreateRequest(BaseModel):
    file_id: Optional[str] = Field(default=None, max_length=64)
    parent_id: Optional[str] = Field(default=None, max_length=64)
    body: str = Field(..., min_length=1, max_length=5000)
    anchor: Optional[CommentAnchor] = None
    quoted_text: str = Field(default="", max_length=2000)


class DocCommentUpdateRequest(BaseModel):
    body: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    status: Optional[Literal["open", "resolved"]] = None


class SuggestionCreateRequest(BaseModel):
    file_id: str = Field(..., max_length=64)
    anchor: CommentAnchor
    original_text: str = Field(default="", max_length=20000)
    proposed_text: str = Field(default="", max_length=20000)
    note: str = Field(default="", max_length=2000)


class WorkspacePrefsRequest(BaseModel):
    prefs: Dict[str, Any] = Field(default_factory=dict)
