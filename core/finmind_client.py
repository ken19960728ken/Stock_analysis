import os

from dotenv import load_dotenv
from FinMind.data import DataLoader

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
            print("✅ FinMind VIP 通道已開啟 (Token 認證成功)")
        except Exception as e:
            print(f"⚠️ FinMind Token 登入失敗 (降級為一般模式): {e}")
    else:
        print("⚠️ 未發現 FINMIND_TOKEN，使用一般限速模式")

    return _fm_loader
