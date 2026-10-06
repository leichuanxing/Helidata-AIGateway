from app.core.exceptions import APIError


def validate(user):
    if user.deleted_at or user.status != 'enabled':
        raise APIError(403, 'USER_DISABLED', '用户已停用')
    if user.must_change_password:
        raise APIError(403, 'PASSWORD_CHANGE_REQUIRED', '请先登录并修改密码')
