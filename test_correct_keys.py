#!/usr/bin/env python3
"""
使用正确密钥测试豆包API连接
"""
import asyncio
import aiohttp
import uuid
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 正确的豆包API密钥
APP_ID = "7059594059"
APP_KEY = "7059594059" 
ACCESS_KEY = "tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt"

async def test_correct_auth():
    """
    使用正确的密钥测试连接
    """
    url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
    
    reqid = str(uuid.uuid4())
    
    headers = {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Request-Id": reqid,
        "X-Api-Access-Key": ACCESS_KEY,
        "X-Api-App-Key": APP_KEY
    }
    
    print("="*60)
    print("🔑 使用正确密钥测试豆包API")
    print("="*60)
    print(f"APP_ID: {APP_ID}")
    print(f"APP_KEY: {APP_KEY}")
    print(f"ACCESS_KEY: {ACCESS_KEY}")
    print(f"URL: {url}")
    print(f"Headers: {headers}")
    print("="*60)
    
    try:
        async with aiohttp.ClientSession() as session:
            print("🔄 正在连接WebSocket...")
            
            async with session.ws_connect(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as ws:
                print("✅ WebSocket连接成功！")
                print("🎉 豆包API认证成功！")
                
                # 关闭连接
                await ws.close()
                return True
                
    except aiohttp.ClientResponseError as e:
        print(f"❌ HTTP错误: {e.status} - {e.message}")
        if e.status == 401:
            print("💡 认证失败 - 请检查密钥是否正确")
        elif e.status == 403:
            print("💡 权限不足 - 请检查服务是否已开通")
        return False
        
    except Exception as e:
        print(f"❌ 连接失败: {type(e).__name__}: {e}")
        return False

async def main():
    success = await test_correct_auth()
    
    if success:
        print("\n🎊 太好了！豆包API连接成功！")
        print("现在可以使用真实的语音识别服务了！")
    else:
        print("\n😞 连接仍然失败")
        print("可能需要进一步检查：")
        print("1. 密钥是否有语音识别权限")
        print("2. 服务是否已正确开通")
        print("3. 是否有IP白名单限制")

if __name__ == "__main__":
    asyncio.run(main())