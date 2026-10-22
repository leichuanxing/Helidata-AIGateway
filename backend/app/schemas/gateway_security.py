from datetime import datetime
from typing import Literal
from ipaddress import ip_network
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class SecurityInput(BaseModel):
    model_config=ConfigDict(extra='forbid')

class AccessRule(SecurityInput):
    enabled: bool = False
    mode: Literal['blacklist','whitelist'] = 'blacklist'
    addresses: list[str] = Field(default_factory=list, max_length=500)

    @field_validator('addresses')
    @classmethod
    def networks(cls, values):
        result = []
        for value in values:
            try:
                network = ip_network(value.strip(), strict=False)
                if network.version==6 and network.prefixlen>=96 and network.network_address.ipv4_mapped is not None:
                    network=ip_network(f'{network.network_address.ipv4_mapped}/{network.prefixlen-96}')
            except ValueError:
                raise ValueError('请输入有效 IP 或 CIDR 网段') from None
            if str(network) not in result: result.append(str(network))
        return result

    @model_validator(mode='after')
    def nonempty(self):
        if self.enabled and self.mode == 'whitelist' and not self.addresses:
            raise ValueError('启用白名单前请添加允许访问的 IP 或网段')
        return self

class KeyBinding(SecurityInput):
    key_id: int = Field(gt=0,strict=True)
    addresses: list[str] = Field(min_length=1, max_length=100)
    _networks = field_validator('addresses')(AccessRule.networks.__func__)

class Ban(SecurityInput):
    address: str
    expires_at: datetime | None = None
    reason: str = Field(default='', max_length=200)
    @field_validator('address')
    @classmethod
    def network(cls, value):
        return AccessRule.networks([value])[0]
    @field_validator('expires_at')
    @classmethod
    def aware(cls, value):
        if value is not None and value.tzinfo is None: raise ValueError('封禁到期时间必须包含时区')
        return value

class SecurityPolicy(SecurityInput):
    revision: int = Field(default=0, ge=0)
    global_access: AccessRule = Field(default_factory=AccessRule)
    admin_access: AccessRule = Field(default_factory=AccessRule)
    api_access: AccessRule = Field(default_factory=AccessRule)
    key_bindings: list[KeyBinding] = Field(default_factory=list, max_length=1000)
    ip_rpm: int = Field(default=0, ge=0, le=1000000)
    key_rpm: int = Field(default=0, ge=0, le=1000000)
    trusted_proxies: list[str] = Field(default_factory=list, max_length=100)
    bans: list[Ban] = Field(default_factory=list, max_length=500)
    login_max_attempts: int = Field(default=5, ge=1, le=50)
    login_lock_seconds: int = Field(default=900, ge=30, le=86400)
    _networks = field_validator('trusted_proxies')(AccessRule.networks.__func__)
    @model_validator(mode='after')
    def unique_bindings(self):
        if len({binding.key_id for binding in self.key_bindings}) != len(self.key_bindings):
            raise ValueError('同一个 API Key 只能配置一组 IP 绑定')
        if len({ban.address for ban in self.bans})!=len(self.bans):
            raise ValueError('同一地址只能配置一条封禁记录，请编辑已有记录')
        if any(ip_network(value).prefixlen == 0 for value in self.trusted_proxies):
            raise ValueError('可信代理不能使用全网网段')
        return self

class SecuritySectionPatch(SecurityInput):
    revision: int = Field(ge=0)
    section: Literal['global_access','admin_access','api_access','rate','login','bans','proxies']
    values: dict

class AddressValidation(SecurityInput):
    addresses: list[str] = Field(min_length=1,max_length=500)
    purpose: Literal['addresses','proxies'] = 'addresses'
