from enum import Enum


class ProjectRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ROLE_RANK: dict[ProjectRole, int] = {
    ProjectRole.VIEWER: 1,
    ProjectRole.REVIEWER: 2,
    ProjectRole.EDITOR: 3,
    ProjectRole.OWNER: 4,
}


class Permission(str, Enum):
    PROJECT_VIEW = "project:view"
    PROJECT_EDIT = "project:edit"
    PROJECT_ADMIN = "project:admin"
    PROJECT_DELETE = "project:delete"
    PUBLICATION_STATUS_MANAGE = "project:publication_status"
    MEMBER_INVITE = "member:invite"
    MEMBER_REMOVE = "member:remove"
    MEMBER_MANAGE = "member:manage"
    TASK_WRITE = "task:write"
    DOC_WRITE = "doc:write"
    DOC_REVIEW = "doc:review"
    LIBRARY_WRITE = "library:write"
    FILE_UPLOAD = "file:upload"
    FILE_DELETE = "file:delete"
    EXPERIMENT_WRITE = "experiment:write"
    DISCUSSION_WRITE = "discussion:write"
    COMMENT_WRITE = "comment:write"


ROLE_PERMISSION_MATRIX: dict[ProjectRole, frozenset[Permission]] = {
    ProjectRole.OWNER: frozenset(Permission),
    ProjectRole.EDITOR: frozenset({
        Permission.PROJECT_VIEW,
        Permission.PROJECT_EDIT,
        Permission.MEMBER_INVITE,
        Permission.TASK_WRITE,
        Permission.DOC_WRITE,
        Permission.DOC_REVIEW,
        Permission.LIBRARY_WRITE,
        Permission.FILE_UPLOAD,
        Permission.FILE_DELETE,
        Permission.EXPERIMENT_WRITE,
        Permission.DISCUSSION_WRITE,
        Permission.COMMENT_WRITE,
    }),
    ProjectRole.REVIEWER: frozenset({
        Permission.PROJECT_VIEW,
        Permission.MEMBER_INVITE,
        Permission.DOC_REVIEW,
        Permission.DISCUSSION_WRITE,
        Permission.COMMENT_WRITE,
    }),
    ProjectRole.VIEWER: frozenset({
        Permission.PROJECT_VIEW,
        Permission.MEMBER_INVITE,
    }),
}


def role_has_permission(role: str | ProjectRole, permission: Permission) -> bool:
    try:
        r = ProjectRole(role) if isinstance(role, str) else role
    except ValueError:
        return False
    return permission in ROLE_PERMISSION_MATRIX.get(r, frozenset())


def can_assign_invitation_role(inviter_role: str | ProjectRole, target_role: str | ProjectRole) -> bool:
    """Ensure an inviter cannot assign a higher role than their own authority permits."""
    try:
        inv_r = ProjectRole(inviter_role) if isinstance(inviter_role, str) else inviter_role
        tgt_r = ProjectRole(target_role) if isinstance(target_role, str) else target_role
    except ValueError:
        return False
    if tgt_r == ProjectRole.OWNER:
        return False
    return ROLE_RANK[inv_r] >= ROLE_RANK[tgt_r]
