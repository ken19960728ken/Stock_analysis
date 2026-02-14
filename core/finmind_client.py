import os

import requests
from dotenv import load_dotenv
from FinMind.data import DataLoader

from core.logger import setup_logger

logger = setup_logger("finmind_client")

load_dotenv()

_fm_loader = None
_fm_token = None


def get_fm_token():
    """返回 FinMind Token 字串（可能為 None）"""
    global _fm_token
    if _fm_token is None:
        _fm_token = os.getenv("FINMIND_TOKEN") or ""
    return _fm_token or None


def get_fm_loader():
    """返回已認證的 FinMind DataLoader 單例"""
    global _fm_loader
    if _fm_loader is not None:
        return _fm_loader

    _fm_loader = DataLoader()
    token = get_fm_token()

    if token:
        try:
            _fm_loader.login_by_token(api_token=token)
            logger.info("FinMind VIP 通道已開啟 (Token 認證成功)")
        except Exception as e:
            logger.warning(f"FinMind Token 登入失敗 (降級為一般模式): {e}")
    else:
        logger.warning("未發現 FINMIND_TOKEN，使用一般限速模式")

    return _fm_loader


def get_api_usage():
    """查詢 FinMind API 使用量，回傳 (user_count, api_request_limit)"""
    token = get_fm_token()
    if not token:
        logger.warning("無 FINMIND_TOKEN，無法查詢 API 使用量")
        return (None, None)

    try:
        resp = requests.get(
            "https://api.web.finmindtrade.com/v2/user_info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        user_count = data.get("user_count")
        api_request_limit = data.get("api_request_limit")
        return (user_count, api_request_limit)
    except Exception as e:
        logger.warning(f"查詢 FinMind API 使用量失敗: {e}")
        return (None, None)
