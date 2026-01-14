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
    # 优先从环境变量获取 COOKIES_DIR
    env_cookies_dir = os.getenv("COOKIES_DIR")
    if env_cookies_dir:
        cookie_dir = Path(env_cookies_dir).absolute()
    else:
        base_dir = Path(__file__).parent.absolute()
        cookie_dir = base_dir / "cookies"
    
    cookie_dir.mkdir(parents=True, exist_ok=True)
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
            
            # 启动前强制验证一次 Cookie 有效性
            # 获取当前 Cookie 路径
            cookie_info = keepalive.get_active_cookie()
            if not cookie_info:
                 raise HTTPException(status_code=400, detail="启动失败: 未找到 Cookie 文件，请先上传")
                 
            _, cookie_path = cookie_info
            
            # 验证 Cookie
            is_valid = await keepalive.validate_cookie(cookie_path)
            if not is_valid:
                 raise HTTPException(status_code=400, detail="启动失败: Cookie 验证无效 (无法访问YouTube)，请重新上传新的 Cookie")

            keepalive.start()
            return {"status": "success", "message": "Cookie 验证通过，保活服务已启动"}

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
