import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

try:
    from pydantic import field_validator as _field_validator
    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import validator as _validator
    _PYDANTIC_V2 = False

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")
# Practical address rules (RFC 5321 limits, dot-atom local part, hostname labels, alphabetic
# top-level domain). Deliverability is proven only by the verification email.
_EMAIL_LOCAL_RE = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_EMAIL_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def clean_username(v: str) -> str:
    cleaned = v.strip().lower()
    if not _USERNAME_RE.match(cleaned):
        raise ValueError("Username must be 3-32 characters using letters, numbers, '_', '.', or '-'.")
    return cleaned


def clean_email(v: str) -> str:
    cleaned = v.strip().lower()
    local, sep, domain = cleaned.rpartition("@")
    labels = domain.split(".")
    if (
        not sep
        or len(cleaned) > 254
        or not 1 <= len(local) <= 64
        or not _EMAIL_LOCAL_RE.match(local)
        or len(labels) < 2
        or not all(_EMAIL_LABEL_RE.match(label) for label in labels)
        or not re.fullmatch(r"[a-z]{2,63}", labels[-1])
    ):
        raise ValueError("Enter a valid email address, like name@university.edu.")
    return cleaned




class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    username: str = Field(..., min_length=3, max_length=32)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=10, max_length=128)

    if _PYDANTIC_V2:
        @_field_validator("username")
        @classmethod
        def validate_username(cls, v: str) -> str:
            return clean_username(v)

        @_field_validator("email")
        @classmethod
        def validate_email(cls, v: str) -> str:
            return clean_email(v)
    else:
        @_validator("username")
        def validate_username(cls, v: str) -> str:
            return clean_username(v)

        @_validator("email")
        def validate_email(cls, v: str) -> str:
            return clean_email(v)


class RegisterEmailCheckRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=254)


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    remember_me: bool = False


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)
    new_password: str = Field(..., min_length=10, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=16, max_length=256)


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    professional_title: Optional[str] = Field(default=None, max_length=120)
    avatar_color: Optional[Literal["indigo", "blue", "violet", "teal", "emerald", "rose", "amber"]] = None
    institution: Optional[str] = Field(default=None, max_length=160)
    department: Optional[str] = Field(default=None, max_length=160)
    bio: Optional[str] = Field(default=None, max_length=1000)
    orcid_id: Optional[str] = Field(default=None, max_length=40)
    research_interests: Optional[List[str]] = None


class PreferencesUpdateRequest(BaseModel):
    theme_mode: Optional[Literal["light", "dark", "system"]] = None
    accent_color: Optional[Literal["indigo", "blue", "violet", "teal", "emerald", "rose", "amber"]] = None
    ui_density: Optional[Literal["compact", "comfortable"]] = None
    reduced_motion: Optional[bool] = None
    notification_preferences: Optional[Dict[str, bool]] = None


class AccountUpdateRequest(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=32)
    new_email: Optional[str] = Field(default=None, min_length=5, max_length=254)

    if _PYDANTIC_V2:
        @_field_validator("username")
        @classmethod
        def validate_optional_username(cls, v: Optional[str]) -> Optional[str]:
            return clean_username(v) if v is not None else None

        @_field_validator("new_email")
        @classmethod
        def validate_optional_email(cls, v: Optional[str]) -> Optional[str]:
            return clean_email(v) if v is not None else None
    else:
        @_validator("username")
        def validate_optional_username(cls, v: Optional[str]) -> Optional[str]:
            return clean_username(v) if v is not None else None

        @_validator("new_email")
        def validate_optional_email(cls, v: Optional[str]) -> Optional[str]:
            return clean_email(v) if v is not None else None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)


class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=3000)
    research_domain: str = Field(default="Computer Science & AI", max_length=120)
    research_questions: List[str] = Field(default_factory=list)
    objectives: List[str] = Field(default_factory=list)
    hypothesis: str = Field(default="", max_length=1500)
    keywords: List[str] = Field(default_factory=list)
    start_date: str = Field(default="", max_length=32)
    target_completion_date: str = Field(default="", max_length=32)
    status: Literal["planning", "active", "completed", "archived"] = "active"
    visibility: Literal["private", "internal"] = "private"
    icon: str = Field(default="microscope", max_length=40)


class ProjectUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=3000)
    research_domain: Optional[str] = Field(default=None, max_length=120)
    research_questions: Optional[List[str]] = None
    objectives: Optional[List[str]] = None
    hypothesis: Optional[str] = Field(default=None, max_length=1500)
    keywords: Optional[List[str]] = None
    status: Optional[Literal["planning", "active", "completed", "archived"]] = None
    visibility: Optional[Literal["private", "internal"]] = None


class InvitationCreateRequest(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=254, description="Username or email of registered user")
    role: Literal["editor", "reviewer", "viewer"] = "editor"
    message: str = Field(default="", max_length=500)


class InvitationRespondRequest(BaseModel):
    action: Literal["accept", "reject", "cancel"]


class MemberRoleUpdateRequest(BaseModel):
    role: Literal["editor", "reviewer", "viewer"]


class OwnershipTransferRequest(BaseModel):
    new_owner_user_id: str = Field(..., min_length=4, max_length=64)


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    status: Literal["todo", "in_progress", "in_review", "done"] = "todo"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    due_date: str = Field(default="", max_length=32)
    milestone_id: Optional[str] = None
    assignee_ids: List[str] = Field(default_factory=list)
    checklist: List[Dict[str, Any]] = Field(default_factory=list)


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["todo", "in_progress", "in_review", "done"]] = None
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = None
    due_date: Optional[str] = Field(default=None, max_length=32)
    assignee_ids: Optional[List[str]] = None
    checklist: Optional[List[Dict[str, Any]]] = None


class DocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content_html: str = Field(default="", max_length=100000)
    is_pinned: bool = False


class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=200)
    content_html: str = Field(..., max_length=100000)
    base_version: int = Field(..., ge=1, description="Expected current_version for optimistic conflict detection")
    change_summary: str = Field(default="Updated document content", max_length=300)
    is_pinned: Optional[bool] = None
    review_status: Optional[Literal["draft", "in_review", "approved", "changes_requested"]] = None


class ReferenceCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=300)
    authors: str = Field(..., min_length=2, max_length=500)
    year: int = Field(..., ge=1900, le=2100)
    doi: str = Field(default="", max_length=160)
    journal_or_conference: str = Field(default="", max_length=200)
    abstract: str = Field(default="", max_length=4000)
    keywords: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)


class ExperimentCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=160)
    objective: str = Field(default="", max_length=1000)
    dataset_ref: str = Field(default="", max_length=160)
    dataset_version: str = Field(default="v1", max_length=40)
    method_or_model: str = Field(..., min_length=2, max_length=160)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    repo_url: str = Field(default="", max_length=300)
    commit_sha: str = Field(default="", max_length=64)
    environment_details: str = Field(default="", max_length=300)
    results_summary: str = Field(default="", max_length=2000)
    status: Literal["queued", "running", "completed", "failed"] = "completed"
    metrics: Dict[str, float] = Field(default_factory=dict)


class DiscussionCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    body: str = Field(..., min_length=1, max_length=4000)


class CommentCreateRequest(BaseModel):
    target_type: Literal["discussion", "task", "document"]
    target_id: str = Field(..., min_length=4, max_length=64)
    body: str = Field(..., min_length=1, max_length=2000)


class ReferenceUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=300)
    authors: Optional[str] = Field(default=None, min_length=2, max_length=500)
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    doi: Optional[str] = Field(default=None, max_length=160)
    journal_or_conference: Optional[str] = Field(default=None, max_length=200)
    abstract: Optional[str] = Field(default=None, max_length=4000)
    notes: Optional[str] = Field(default=None, max_length=2000)
    keywords: Optional[List[str]] = None
    tags: Optional[List[str]] = None


class ExperimentUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    objective: Optional[str] = Field(default=None, max_length=1000)
    results_summary: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["queued", "running", "completed", "failed"]] = None
    metrics: Optional[Dict[str, float]] = None


PUBLICATION_STATUS_VALUES = Literal[
    "Research in Progress",
    "Drafting",
    "Under Internal Review",
    "Ready for Submission",
    "Submitted",
    "Under Review",
    "Revision Requested",
    "Accepted",
    "Published",
    "Rejected",
    "Archived",
]

DRAFT_STATUS_VALUES = Literal[
    "Working Draft",
    "Internal Review",
    "Ready for Submission",
    "Submitted",
    "Published",
    "Archived",
]


class PublicationStatusUpdateRequest(BaseModel):
    publication_status: PUBLICATION_STATUS_VALUES


class UploadInitRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=240)
    folder: str = Field(default="/", max_length=200)
    artifact_type: str = Field(default="dataset", max_length=40)
    total_size_bytes: int = Field(..., ge=1)
    total_chunks: int = Field(default=1, ge=1)


class FileMetadataUpdateRequest(BaseModel):
    original_name: Optional[str] = Field(default=None, min_length=1, max_length=240)
    folder: Optional[str] = Field(default=None, max_length=200)
    tags: Optional[List[str]] = None
    linked_entity_type: Optional[str] = Field(default=None, max_length=64)
    linked_entity_id: Optional[str] = Field(default=None, max_length=64)


class ArtifactCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    artifact_type: Literal["code", "dataset", "notebook", "result", "figure", "log", "checkpoint"] = "code"
    language: str = Field(default="python", max_length=40)
    content_text: str = Field(default="", max_length=500000)
    metrics: Dict[str, float] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    unit_system: str = Field(default="SI", max_length=40)
    linked_experiment_id: str = Field(default="", max_length=64)
    linked_dataset_version: str = Field(default="v1", max_length=40)
    linked_code_version: str = Field(default="v1", max_length=40)
    linked_paper_section: str = Field(default="", max_length=120)
    tags: List[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)


class CodeComparisonRequest(BaseModel):
    left_title: str = Field(default="Version A", max_length=200)
    right_title: str = Field(default="Version B", max_length=200)
    left_code: str = Field(..., max_length=500000)
    right_code: str = Field(..., max_length=500000)


class ResultComparisonRequest(BaseModel):
    artifact_ids: List[str] = Field(default_factory=list)
    experiment_ids: List[str] = Field(default_factory=list)


class CollaborationSignalCreateRequest(BaseModel):
    message: str = Field(default="", max_length=500)
    proposed_contribution: str = Field(default="", max_length=500)


class CollaborationSignalUpdateRequest(BaseModel):
    status: Literal["Pending", "Acknowledged", "Accepted", "Declined"]
