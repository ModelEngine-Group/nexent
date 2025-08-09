import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request, HTTPException
from consts.const import DEFAULT_USER_ID, DEFAULT_TENANT_ID, IS_SPEED_MODE
import jwt
from supabase import create_client
from database.user_tenant_db import get_user_tenant_by_user_id

# Get Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL', 'http://118.31.249.152:8010')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')
# 调试用 JWT 过期时间（秒），未设置或为 0 表示不生效
DEBUG_JWT_EXPIRE_SECONDS = int(os.getenv('DEBUG_JWT_EXPIRE_SECONDS', '0') or 0)

def get_supabase_client():
    """获取Supabase客户端实例"""
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logging.error(f"创建Supabase客户端失败: {str(e)}")
        return None


def get_jwt_expiry_seconds(token: str) -> int:
    """
    从JWT令牌中获取过期时间（秒）

    Args:
        token: JWT令牌字符串

    Returns:
        int: 令牌的有效期（秒），如果解析失败则返回默认值3600
    """
    try:
        # 确保token是纯JWT，去除可能的Bearer前缀
        jwt_token = token.replace("Bearer ", "") if token.startswith("Bearer ") else token

        # 如果设置了调试过期时间，直接返回以便快速调试
        if DEBUG_JWT_EXPIRE_SECONDS > 0:
            return DEBUG_JWT_EXPIRE_SECONDS

        # 解码JWT令牌(不验证签名，只解析内容)
        decoded = jwt.decode(jwt_token, options={"verify_signature": False})

        # 从JWT声明中提取过期时间和签发时间
        exp = decoded.get("exp", 0)
        iat = decoded.get("iat", 0)

        # 计算有效期（秒）
        expiry_seconds = exp - iat

        return expiry_seconds
    except Exception as e:
        logging.warning(f"从令牌获取过期时间失败: {str(e)}")
        return 3600  # supabase默认设置


def calculate_expires_at(token: Optional[str] = None) -> int:
    """
    计算会话过期时间（与Supabase JWT过期时间保持一致）

    Args:
        token: 可选的JWT令牌，用于获取实际过期时间

    Returns:
        int: 过期时间的时间戳
    """
    expiry_seconds = get_jwt_expiry_seconds(token) if token else 3600
    return int((datetime.now() + timedelta(seconds=expiry_seconds)).timestamp())


def get_current_user_id_from_token(authorization: str) -> Optional[str]:
    """
    Extract user ID from JWT token

    Args:
        authorization: Authorization header value

    Returns:
        Optional[str]: User ID, return None if parsing fails
    """
    # 当IS_SPEED_MODE为True时，直接返回默认用户ID
    if IS_SPEED_MODE:
        logging.debug("Speed mode detected - returning default user ID")
        return DEFAULT_USER_ID
    
    try:
        # 格式化授权头部
        token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

        # 解码JWT令牌(不验证签名，只解析内容)
        decoded = jwt.decode(token, options={"verify_signature": False})

        # 从JWT声明中提取用户ID
        user_id = decoded.get("sub")

        return user_id
    except Exception as e:
        logging.error(f"Failed to extract user ID from token: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")


def get_current_user_id(authorization: Optional[str] = None) -> tuple[str, str]:
    """
    Get current user ID and tenant ID from authorization token

    Args:
        authorization: Authorization header value

    Returns:
        tuple[str, str]: (user_id, tenant_id)
    """
    # 当IS_SPEED_MODE为True时，直接返回默认值
    if IS_SPEED_MODE:
        logging.debug("Speed mode detected - returning default user ID and tenant ID")
        return DEFAULT_USER_ID, DEFAULT_TENANT_ID

    try:
        user_id = get_current_user_id_from_token(str(authorization))
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired authentication token")

        user_tenant_record = get_user_tenant_by_user_id(user_id)
        if user_tenant_record and user_tenant_record.get('tenant_id'):
            tenant_id = user_tenant_record['tenant_id']
            logging.debug(f"Found tenant ID for user {user_id}: {tenant_id}")
        else:
            tenant_id = DEFAULT_TENANT_ID
            logging.warning(f"No tenant relationship found for user {user_id}, using default tenant")

        return user_id, tenant_id

    except Exception as e:
        logging.error(f"Failed to get user ID and tanent ID: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")


def get_user_language(request: Request = None) -> str:
    """
    Get user language preference from request

    Args:
        request: FastAPI request object, used to get cookie

    Returns:
        str: Language code ('zh' or 'en'), default to 'zh'
    """
    default_language = 'zh'

    # Read language setting from cookie
    if request:
        try:
            if hasattr(request, 'cookies') and request.cookies:
                cookie_locale = request.cookies.get('NEXT_LOCALE')
                if cookie_locale and cookie_locale in ['zh', 'en']:
                    return cookie_locale
        except (AttributeError, TypeError) as e:
            logging.warning(f"Error reading language from cookies: {e}")

    return default_language


def get_current_user_info(authorization: Optional[str] = None, request: Request = None) -> tuple[str, str, str]:
    """
    Get current user information, including user ID, tenant ID, and language preference

    Args:
        authorization: Authorization header value
        request: FastAPI request object

    Returns:
        tuple[str, str, str]: (User ID, Tenant ID, Language code)
    """
    user_id, tenant_id = get_current_user_id(authorization)
    language = get_user_language(request)
    return user_id, tenant_id, language
