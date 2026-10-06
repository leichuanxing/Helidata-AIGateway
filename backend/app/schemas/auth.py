from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator,model_validator
from app.core.security import validate_password


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128, repr=False)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128, repr=False)
    new_password: str = Field(min_length=12, max_length=128, repr=False)

    @field_validator('new_password')
    @classmethod
    def strong(cls, value):
        if not validate_password(value):
            raise ValueError('密码至少12位，且包含大小写字母、数字、符号中的三类')
        return value


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='', max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)


class UserEdit(Profile):
    remark: str=Field(default='',max_length=2000)
    role: Literal['super_admin','admin','user'] = 'user'
    status: Literal['enabled','disabled'] = 'enabled'
    user_group_id: int | None = Field(default=None, gt=0)


class UserCreate(UserEdit):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str | None = Field(default=None, max_length=128, repr=False)
    password_confirmation: str | None=Field(default=None,max_length=128,repr=False)

    @model_validator(mode='after')
    def confirm(self):
        if self.password_confirmation is not None and self.password_confirmation!=self.password:
            raise ValueError('两次密码输入不一致')
        return self

    @field_validator('password')
    @classmethod
    def strong(cls, value):
        if value is not None and not validate_password(value):
            raise ValueError('密码复杂度不足')
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    name: str
    email: str | None
    phone: str | None
    remark: str=''
    role: str
    status: str
    user_group_id: int | None
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime


def public_user(user):
    return UserOut.model_validate(user).model_dump(mode='json')


class AdminPasswordReset(BaseModel):
    model_config=ConfigDict(extra='forbid')
    password: str=Field(min_length=12,max_length=128,repr=False)
    password_confirmation: str=Field(min_length=12,max_length=128,repr=False)

    @model_validator(mode='after')
    def check_confirmation(self):
        if self.password!=self.password_confirmation:raise ValueError('两次密码输入不一致')
        if not validate_password(self.password):raise ValueError('密码复杂度不足')
        return self
