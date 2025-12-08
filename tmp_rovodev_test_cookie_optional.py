"""
测试 cookie 字符串参数功能
"""
import requests
import json

BASE_URL = "http://localhost:24314"
API_TOKEN = "Abcd123456"

headers = {
    "X-API-Token": API_TOKEN,
    "Content-Type": "application/json"
}

def test_download_without_cookie():
    """测试不传 cookie 参数（使用本地cookie文件）"""
    print("\n========== 测试1: 不传 cookie 参数（使用本地文件）==========")
    
    payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "subtitle_lang": "en"
    }
    
    print(f"请求体: {json.dumps(payload, indent=2)}")
    
    # 注意：这个请求可能会失败（如果视频不存在或无字幕），但我们主要是测试参数是否正确
    try:
        response = requests.post(
            f"{BASE_URL}/subtitle/download",
            headers=headers,
            json=payload,
            timeout=30
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求异常: {e}")

def test_download_with_cookie_string():
    """测试传 cookie 字符串参数"""
    print("\n========== 测试2: 传 cookie 字符串参数 ==========")
    
    # 模拟cookie字符串内容
    cookie_content = """# Netscape HTTP Cookie File
# This is a generated file! Do not edit.
.youtube.com	TRUE	/	TRUE	0	CONSENT	YES+1
.youtube.com	TRUE	/	FALSE	0	VISITOR_INFO1_LIVE	test_value
"""
    
    # 测试下载时传入cookie字符串
    payload = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "cookie": cookie_content,
        "subtitle_lang": "en"
    }
    
    print(f"请求体: {json.dumps({**payload, 'cookie': '...(cookie内容已省略)...'}, indent=2)}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/subtitle/download",
            headers=headers,
            json=payload,
            timeout=30
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求异常: {e}")

def test_prepare_local_cookie():
    """准备本地cookie文件用于测试1"""
    print("\n========== 准备: 保存本地cookie文件 ==========")
    
    save_payload = {
        "cookie_name": "test_local_cookie",
        "cookie_content": "# Netscape HTTP Cookie File\n# Test local cookie\n.youtube.com\tTRUE\t/\tTRUE\t0\tCONSENT\tYES+1\n"
    }
    
    try:
        save_response = requests.post(
            f"{BASE_URL}/cookie/save",
            headers=headers,
            json=save_payload
        )
        print(f"保存Cookie响应: {save_response.json()}")
        return True
    except Exception as e:
        print(f"保存Cookie失败: {e}")
        return False

def test_health():
    """测试健康检查"""
    print("\n========== 测试0: 健康检查 ==========")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200
    except Exception as e:
        print(f"健康检查失败: {e}")
        return False

if __name__ == "__main__":
    print("开始测试 cookie 字符串参数功能...")
    
    if not test_health():
        print("\n❌ 服务未启动，请先启动服务：python main.py")
        exit(1)
    
    # 准备本地cookie文件
    test_prepare_local_cookie()
    
    # 测试1: 不传cookie参数（使用本地文件）
    test_download_without_cookie()
    
    # 测试2: 传cookie字符串参数
    test_download_with_cookie_string()
    
    print("\n========== 测试完成 ==========")
    print("✅ 新的API设计:")
    print("  1. 可以传 'cookie' 字符串参数")
    print("  2. 不传则自动使用本地 ./cookies/ 目录的文件")
    print("  3. 不再需要通过 cookie_file 指定文件名")
    print("\n注意：如果看到404或500错误，这是正常的（测试视频可能不存在或无字幕）")
    print("重点是检查参数是否被正确接受，以及cookie_source字段的值")
