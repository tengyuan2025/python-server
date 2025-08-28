#!/usr/bin/env python3
"""
测试豆包API认证的脚本
"""
import asyncio
import aiohttp
import uuid
import logging

# 配置日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 您的密钥信息
APP_KEY = "35ef5232-453b-45e3-9bf7-06138ff77dc9"  # API Key
ACCESS_KEY_ENCODED = "TlRJMU5tWTVPVEpqTmpRd05EWTJNVGcyTkdGek56QmxNREV4WVdaaE5qVQ=="  # Access Key (Base64编码)
ACCESS_KEY_DECODED = "NTI1NmY5OTJjNjQwNDY2MTg2NGFzNzBlMDExYWZhNjU"  # Access Key (解码后)
APP_ID = "7059594059"

# 测试用的WebSocket URL
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

async def test_websocket_connection():
    """
    测试WebSocket连接和认证
    """
    reqid = str(uuid.uuid4())
    
    # 构建请求头
    headers = {
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Request-Id": reqid,
        "X-Api-Access-Key": ACCESS_KEY,
        "X-Api-App-Key": APP_KEY
    }
    
    logger.info("尝试连接WebSocket...")
    logger.info(f"URL: {WS_URL}")
    logger.info(f"Headers: {headers}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL, headers=headers) as ws:
                logger.info("✅ WebSocket连接成功！")
                logger.info("认证参数正确")
                return True
                
    except aiohttp.ClientResponseError as e:
        logger.error(f"❌ HTTP错误 {e.status}: {e.message}")
        if e.status == 401:
            logger.error("认证失败，可能的原因：")
            logger.error("1. APP_KEY或ACCESS_KEY不正确")
            logger.error("2. 密钥格式不对")
            logger.error("3. 权限不足")
            logger.error("4. 请检查火山引擎控制台的密钥配置")
        return False
        
    except Exception as e:
        logger.error(f"❌ 连接失败: {e}")
        return False

async def test_different_auth_combinations():
    """
    尝试不同的认证组合
    """
    combinations = [
        # 使用编码的Access Key
        {
            "app_key": APP_KEY,
            "access_key": ACCESS_KEY_ENCODED,
            "name": "API_KEY + ACCESS_KEY(编码)"
        },
        # 使用解码的Access Key
        {
            "app_key": APP_KEY,
            "access_key": ACCESS_KEY_DECODED,
            "name": "API_KEY + ACCESS_KEY(解码)"
        },
        # 使用APP_ID作为app_key
        {
            "app_key": APP_ID,
            "access_key": ACCESS_KEY_ENCODED,
            "name": "APP_ID + ACCESS_KEY(编码)"
        },
        # 使用APP_ID和解码的Access Key
        {
            "app_key": APP_ID,
            "access_key": ACCESS_KEY_DECODED,
            "name": "APP_ID + ACCESS_KEY(解码)"
        }
    ]
    
    for i, combo in enumerate(combinations, 1):
        logger.info(f"\n--- 测试组合 {i}: {combo['name']} ---")
        
        reqid = str(uuid.uuid4())
        headers = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": combo["access_key"],
            "X-Api-App-Key": combo["app_key"]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(WS_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as ws:
                    logger.info(f"✅ 组合 {i} 连接成功！")
                    logger.info(f"正确的配置: app_key={combo['app_key']}, access_key={combo['access_key']}")
                    return combo
                    
        except aiohttp.ClientResponseError as e:
            logger.error(f"❌ 组合 {i} 失败: HTTP {e.status}")
            
        except Exception as e:
            logger.error(f"❌ 组合 {i} 失败: {e}")
            
        await asyncio.sleep(1)  # 避免请求过快
    
    return None

async def main():
    print("="*60)
    print("🔑 豆包API认证测试工具")
    print("="*60)
    print(f"APP_ID: {APP_ID}")
    print(f"APP_KEY: {APP_KEY}")
    print(f"ACCESS_KEY(编码): {ACCESS_KEY_ENCODED}")
    print(f"ACCESS_KEY(解码): {ACCESS_KEY_DECODED}")
    print("="*60)
    
    # 测试不同的认证组合
    success_combo = await test_different_auth_combinations()
    
    if success_combo:
        print("\n🎉 找到正确的认证配置！")
        print(f"app_key: {success_combo['app_key']}")
        print(f"access_key: {success_combo['access_key']}")
    else:
        print("\n❌ 所有认证组合都失败了")
        print("\n💡 解决方案：")
        print("1. 请登录火山引擎控制台")
        print("2. 进入语音识别服务页面")
        print("3. 查看应用管理，确认APP_KEY和ACCESS_KEY")
        print("4. 确保服务已开通并有权限")
        print("5. 检查密钥是否过期")

if __name__ == "__main__":
    asyncio.run(main())