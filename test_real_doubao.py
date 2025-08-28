#!/usr/bin/env python3
"""
直接使用官方demo逻辑测试豆包API
"""
import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
import tempfile
import os

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 您的密钥配置
class Config:
    def __init__(self):
        # 使用正确的豆包API密钥
        self.auth = {
            "app_key": "7059594059",  # App Key
            "access_key": "tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt"  # Access Key
        }

    @property
    def app_key(self) -> str:
        return self.auth["app_key"]

    @property
    def access_key(self) -> str:
        return self.auth["access_key"]

config = Config()

# 常量定义（完全按照官方demo）
class ProtocolVersion:
    V1 = 0b0001

class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111

class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011

class SerializationType:
    NO_SERIALIZATION = 0b0000
    JSON = 0b0001

class CompressionType:
    GZIP = 0b0001

class CommonUtils:
    @staticmethod
    def gzip_compress(data: bytes) -> bytes:
        return gzip.compress(data)

    @staticmethod
    def gzip_decompress(data: bytes) -> bytes:
        return gzip.decompress(data)

class AsrRequestHeader:
    def __init__(self):
        self.message_type = MessageType.CLIENT_FULL_REQUEST
        self.message_type_specific_flags = MessageTypeSpecificFlags.POS_SEQUENCE
        self.serialization_type = SerializationType.JSON
        self.compression_type = CompressionType.GZIP
        self.reserved_data = bytes([0x00])

    def with_message_type(self, message_type: int):
        self.message_type = message_type
        return self

    def with_message_type_specific_flags(self, flags: int):
        self.message_type_specific_flags = flags
        return self

    def to_bytes(self) -> bytes:
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)
        header.append((self.message_type << 4) | self.message_type_specific_flags)
        header.append((self.serialization_type << 4) | self.compression_type)
        header.extend(self.reserved_data)
        return bytes(header)

    @staticmethod
    def default_header():
        return AsrRequestHeader()

class RequestBuilder:
    @staticmethod
    def new_auth_headers():
        reqid = str(uuid.uuid4())
        return {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": config.access_key,
            "X-Api-App-Key": config.app_key
        }

    @staticmethod
    def new_full_client_request(seq: int) -> bytes:
        header = AsrRequestHeader.default_header().with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        
        payload = {
            "user": {
                "uid": "demo_uid"
            },
            "audio": {
                "format": "wav",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False
            }
        }
        
        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = CommonUtils.gzip_compress(payload_bytes)
        payload_size = len(compressed_payload)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        request.extend(struct.pack('>I', payload_size))
        request.extend(compressed_payload)
        
        return bytes(request)

async def test_connection_detailed():
    """
    详细测试连接，并检查可能的问题
    """
    url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
    
    # 尝试不同的配置组合
    test_configs = [
        {
            "app_key": "35ef5232-453b-45e3-9bf7-06138ff77dc9",
            "access_key": "NTI1NmY5OTJjNjQwNDY2MTg2NGFzNzBlMDExYWZhNjU",
            "name": "解码后的Access Key"
        },
        {
            "app_key": "35ef5232-453b-45e3-9bf7-06138ff77dc9", 
            "access_key": "TlRJMU5tWTVPVEpqTmpRd05EWTJNVGcyTkdFek56QmxNREV4WVdaaE5qVQ==",
            "name": "原始Base64 Access Key"
        },
        {
            "app_key": "7059594059",
            "access_key": "35ef5232-453b-45e3-9bf7-06138ff77dc9", 
            "name": "APP_ID作为app_key，API_KEY作为access_key"
        }
    ]
    
    for i, test_config in enumerate(test_configs, 1):
        print(f"\n--- 测试配置 {i}: {test_config['name']} ---")
        
        # 临时修改config
        original_app_key = config.auth["app_key"]
        original_access_key = config.auth["access_key"]
        
        config.auth["app_key"] = test_config["app_key"]
        config.auth["access_key"] = test_config["access_key"]
        
        try:
            headers = RequestBuilder.new_auth_headers()
            print(f"请求头: {headers}")
            
            async with aiohttp.ClientSession() as session:
                print(f"尝试连接: {url}")
                
                try:
                    async with session.ws_connect(url, headers=headers) as ws:
                        print("✅ WebSocket连接成功!")
                        
                        # 尝试发送初始请求
                        seq = 1
                        request = RequestBuilder.new_full_client_request(seq)
                        
                        await ws.send_bytes(request)
                        print("✅ 发送初始请求成功!")
                        
                        # 接收响应
                        msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            print("✅ 收到服务器响应!")
                            print(f"响应数据长度: {len(msg.data)} bytes")
                            
                            # 这里证明认证成功了
                            print(f"🎉 认证成功! 使用配置: {test_config['name']}")
                            print(f"正确的app_key: {test_config['app_key']}")
                            print(f"正确的access_key: {test_config['access_key']}")
                            
                            return test_config
                        else:
                            print(f"❌ 收到非预期消息类型: {msg.type}")
                            
                except aiohttp.ClientResponseError as e:
                    print(f"❌ HTTP错误: {e.status} - {e.message}")
                    if e.status == 401:
                        print("   认证失败，检查密钥是否正确")
                    elif e.status == 403:
                        print("   权限不足，检查服务是否已开通")
                        
                except Exception as e:
                    print(f"❌ 连接失败: {type(e).__name__}: {e}")
                    
        finally:
            # 恢复原始配置
            config.auth["app_key"] = original_app_key
            config.auth["access_key"] = original_access_key
            
        await asyncio.sleep(1)  # 避免请求过快
    
    print("\n❌ 所有配置都无法成功连接")
    return None

async def main():
    print("="*60)
    print("🔑 豆包API真实连接测试")
    print("="*60)
    
    success_config = await test_connection_detailed()
    
    if success_config:
        print("\n✅ 找到有效的认证配置!")
        print("请在您的Flask应用中使用以下配置:")
        print(f"APP_KEY = \"{success_config['app_key']}\"")
        print(f"ACCESS_KEY = \"{success_config['access_key']}\"")
    else:
        print("\n❌ 无法找到有效的认证配置")
        print("\n可能的问题：")
        print("1. 密钥已过期或无效")
        print("2. 服务未正确开通")
        print("3. 需要其他格式的密钥")
        print("4. IP地址不在白名单中")
        print("\n建议：")
        print("1. 登录火山引擎控制台确认密钥")
        print("2. 检查语音识别服务状态") 
        print("3. 查看API文档确认认证格式")

if __name__ == "__main__":
    asyncio.run(main())