from app.core.exceptions import APIError


def validate(group):
    if not group:
        raise APIError(403, 'GROUP_REQUIRED', '用户尚未分配用户组')
    if group.status != 'enabled':
        raise APIError(403, 'GROUP_DISABLED', '用户组已停用')
