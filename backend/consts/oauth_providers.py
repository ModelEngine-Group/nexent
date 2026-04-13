import os
from typing import Dict

from consts.model import OAuthProviderDefinition

GITHUB_PROVIDER = OAuthProviderDefinition(
    name="github",
    display_name="GitHub",
    icon="github",
    authorize_url="https://github.com/login/oauth/authorize",
    authorize_params={"scope": "read:user user:email"},
    token_url="https://github.com/login/oauth/access_token",
    token_error_key="error",
    token_error_message_key="error_description",
    userinfo_url="https://api.github.com/user",
    userinfo_field_map={
        "id": "id",
        "email": "email",
        "username": "login",
        "avatar_url": "avatar_url",
    },
    userinfo_needs_email_fetch=True,
    userinfo_email_url="https://api.github.com/user/emails",
    client_id_env="GITHUB_OAUTH_CLIENT_ID",
    client_secret_env="GITHUB_OAUTH_CLIENT_SECRET",
)

WECHAT_PROVIDER = OAuthProviderDefinition(
    name="wechat",
    display_name="WeChat",
    icon="wechat",
    authorize_url="https://open.weixin.qq.com/connect/qrconnect",
    authorize_params={"response_type": "code", "scope": "snsapi_login"},
    authorize_fragment="#wechat_redirect",
    authorize_param_map={
        "client_id": "appid",
        "redirect_uri": "redirect_uri",
        "scope": "scope",
        "state": "state",
    },
    encode_redirect_uri=True,
    token_url="https://api.weixin.qq.com/sns/oauth2/access_token",
    token_method="GET",
    token_params_map={
        "client_id": "appid",
        "client_secret": "secret",
        "code": "code",
        "grant_type": "grant_type",
    },
    token_error_key="errcode",
    token_error_message_key="errmsg",
    token_response_id_key="openid",
    userinfo_url="https://api.weixin.qq.com/sns/userinfo",
    userinfo_auth_scheme="",
    userinfo_params={"openid": "{openid}"},
    userinfo_field_map={
        "id": "openid",
        "email": "",
        "username": "nickname",
        "avatar_url": "headimgurl",
    },
    client_id_env="WECHAT_OAUTH_APP_ID",
    client_secret_env="WECHAT_OAUTH_APP_SECRET",
    enabled_check="ENABLE_WECHAT_OAUTH",
)

OAUTH_PROVIDER_REGISTRY: Dict[str, OAuthProviderDefinition] = {
    "github": GITHUB_PROVIDER,
    "wechat": WECHAT_PROVIDER,
}


def get_provider_definition(provider: str) -> OAuthProviderDefinition:
    return OAUTH_PROVIDER_REGISTRY[provider]


def is_provider_enabled(definition: OAuthProviderDefinition) -> bool:
    if definition.enabled_check:
        return os.getenv(definition.enabled_check, "false").lower() in (
            "true",
            "1",
            "yes",
        )

    client_id = os.getenv(definition.client_id_env, "")
    client_secret = os.getenv(definition.client_secret_env, "")
    return bool(client_id and client_secret)


def get_all_provider_definitions() -> Dict[str, OAuthProviderDefinition]:
    return dict(OAUTH_PROVIDER_REGISTRY)
