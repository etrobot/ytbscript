from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pathlib import Path
import os

from cookie_keepalive_service import get_keepalive_service

router = APIRouter()

API_TOKEN = os.getenv("API_TOKEN", "Abcd123456")

security = HTTPBearer(auto_error=False)


async def verify_any_token(
    x_api_token: str = Header(None, alias="X-API-Token"),
    bearer_token: HTTPAuthorizationCredentials = Depends(security),
):
    if x_api_token:
        if x_api_token == API_TOKEN:
            return True
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的API Token")

    if bearer_token:
        if bearer_token.credentials == API_TOKEN:
            return True
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的Bearer Token")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少API Token，请在请求头中添加 X-API-Token",
    )


def _get_cookie_dir() -> Path:
    base_dir = Path(__file__).parent.absolute()
    cookie_dir = base_dir / "cookies"
    cookie_dir.mkdir(exist_ok=True)
    return cookie_dir


@router.get("/api/cookie/keepalive/status")
async def get_keepalive_status(token_valid: bool = Depends(verify_any_token)):
    try:
        keepalive = get_keepalive_service(_get_cookie_dir())
        status = keepalive.get_status()
        return {"status": "success", "keepalive_service": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取保活状态失败: {str(e)}")


@router.post("/api/cookie/keepalive/control")
async def control_keepalive(action: str, token_valid: bool = Depends(verify_any_token)):
    try:
        keepalive = get_keepalive_service(_get_cookie_dir())

        if action == "start":
            if keepalive.running:
                return {"status": "info", "message": "保活服务已在运行"}
            keepalive.start()
            return {"status": "success", "message": "保活服务已启动"}

        if action == "pause":
            keepalive.pause()
            return {"status": "success", "message": "保活服务已暂停"}

        if action == "resume":
            keepalive.resume()
            return {"status": "success", "message": "保活服务已恢复"}

        if action == "stop":
            await keepalive.stop()
            return {"status": "success", "message": "保活服务已停止"}

        raise HTTPException(status_code=400, detail=f"无效的操作: {action}")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"控制保活服务失败: {str(e)}")
