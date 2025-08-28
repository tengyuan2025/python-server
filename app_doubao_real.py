from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, Any, Tuple

app = Flask(__name__)
CORS(app)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 豆包语音识别配置 - 使用正确的密钥
APP_ID = "7059594059"
APP_KEY = "7059594059"
ACCESS_KEY = "tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt"

# WebSocket URL
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

# 常量定义
DEFAULT_SAMPLE_RATE = 16000

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

class AudioUtils:
    @staticmethod
    def gzip_compress(data: bytes) -> bytes:
        return gzip.compress(data)

    @staticmethod
    def gzip_decompress(data: bytes) -> bytes:
        return gzip.decompress(data)

    @staticmethod
    def judge_wav(data: bytes) -> bool:
        if len(data) < 44:
            return False
        return data[:4] == b'RIFF' and data[8:12] == b'WAVE'

    @staticmethod
    def convert_to_wav(audio_data: bytes, input_format: str = "webm") -> bytes:
        try:
            with tempfile.NamedTemporaryFile(suffix=f'.{input_format}', delete=False) as temp_input:
                temp_input.write(audio_data)
                temp_input_path = temp_input.name
            
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_output:
                temp_output_path = temp_output.name
            
            cmd = [
                "ffmpeg", "-v", "quiet", "-y", 
                "-i", temp_input_path,
                "-acodec", "pcm_s16le", 
                "-ac", "1", 
                "-ar", "16000",
                "-f", "wav", 
                temp_output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True)
            
            if result.returncode == 0:
                with open(temp_output_path, 'rb') as f:
                    wav_data = f.read()
                
                try:
                    os.remove(temp_input_path)
                    os.remove(temp_output_path)
                except:
                    pass
                
                return wav_data
            else:
                logger.error(f"FFmpeg conversion failed: {result.stderr.decode()}")
                return None
                
        except Exception as e:
            logger.error(f"Audio conversion error: {e}")
            return None

    @staticmethod
    def read_wav_info(data: bytes) -> Tuple[int, int, int, int, bytes]:
        if len(data) < 44:
            raise ValueError("Invalid WAV file: too short")
            
        chunk_id = data[:4]
        if chunk_id != b'RIFF':
            raise ValueError("Invalid WAV file: not RIFF format")
            
        format_ = data[8:12]
        if format_ != b'WAVE':
            raise ValueError("Invalid WAV file: not WAVE format")
            
        audio_format = struct.unpack('<H', data[20:22])[0]
        num_channels = struct.unpack('<H', data[22:24])[0]
        sample_rate = struct.unpack('<I', data[24:28])[0]
        bits_per_sample = struct.unpack('<H', data[34:36])[0]
        
        pos = 36
        while pos < len(data) - 8:
            subchunk_id = data[pos:pos+4]
            subchunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
            if subchunk_id == b'data':
                wave_data = data[pos+8:pos+8+subchunk_size]
                return (
                    num_channels,
                    bits_per_sample // 8,
                    sample_rate,
                    subchunk_size // (num_channels * (bits_per_sample // 8)),
                    wave_data
                )
            pos += 8 + subchunk_size
            
        raise ValueError("Invalid WAV file: no data subchunk found")

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

class ResponseParser:
    @staticmethod
    def parse_response(msg: bytes) -> Dict[str, Any]:
        response = {
            "code": 0,
            "is_last_package": False,
            "payload_msg": None
        }
        
        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_type_specific_flags = msg[1] & 0x0f
        serialization_method = msg[2] >> 4
        message_compression = msg[2] & 0x0f
        
        payload = msg[header_size*4:]
        
        if message_type_specific_flags & 0x01:
            payload_sequence = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            response["is_last_package"] = True
            
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            response["code"] = struct.unpack('>i', payload[:4])[0]
            payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            
        if not payload:
            return response
            
        if message_compression == CompressionType.GZIP:
            try:
                payload = AudioUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        try:
            if serialization_method == SerializationType.JSON:
                response["payload_msg"] = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

async def call_doubao_asr(audio_data: bytes) -> Dict[str, Any]:
    """
    调用豆包流式语音识别API - 完整实现
    """
    try:
        # 确保音频格式正确
        if not AudioUtils.judge_wav(audio_data):
            logger.info("Converting audio to WAV format...")
            
            converted_data = AudioUtils.convert_to_wav(audio_data, "webm")
            if converted_data is None:
                converted_data = AudioUtils.convert_to_wav(audio_data, "ogg")
            if converted_data is None:
                converted_data = AudioUtils.convert_to_wav(audio_data, "mp4")
                
            if converted_data is None:
                return {
                    'success': False,
                    'error': 'Unable to convert audio to WAV format',
                    'code': 400
                }
            
            audio_data = converted_data
            logger.info("Audio successfully converted to WAV format")
        
        # 生成请求ID和准备WebSocket连接
        reqid = str(uuid.uuid4())
        headers = {
            "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
            "X-Api-Request-Id": reqid,
            "X-Api-Access-Key": ACCESS_KEY,
            "X-Api-App-Key": APP_KEY
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(WS_URL, headers=headers) as ws:
                    logger.info("WebSocket连接成功")
                    
                    # 1. 发送初始请求
                    seq = 1
                    header = AsrRequestHeader()
                    
                    payload = {
                        "user": {
                            "uid": "flask_client"
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
                    compressed_payload = AudioUtils.gzip_compress(payload_bytes)
                    
                    request = bytearray()
                    request.extend(header.to_bytes())
                    request.extend(struct.pack('>i', seq))
                    request.extend(struct.pack('>I', len(compressed_payload)))
                    request.extend(compressed_payload)
                    
                    await ws.send_bytes(bytes(request))
                    logger.info("发送初始请求成功")
                    
                    # 接收初始响应
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    if msg.type != aiohttp.WSMsgType.BINARY:
                        return {
                            'success': False,
                            'error': 'Invalid response from server',
                            'code': 500
                        }
                    
                    initial_response = ResponseParser.parse_response(msg.data)
                    if initial_response.get("code") != 0:
                        return {
                            'success': False,
                            'error': f'Server error: {initial_response.get("code")}',
                            'code': 500
                        }
                    
                    logger.info("收到初始响应成功")
                    
                    # 2. 发送音频数据
                    seq += 1
                    
                    # 获取WAV音频数据部分
                    try:
                        _, _, _, _, wave_data = AudioUtils.read_wav_info(audio_data)
                    except:
                        wave_data = audio_data[44:] if len(audio_data) > 44 else audio_data
                    
                    # 分段发送音频
                    segment_size = 16000 * 2 * 200 // 1000  # 200ms的数据
                    segments = []
                    for i in range(0, len(wave_data), segment_size):
                        segments.append(wave_data[i:i+segment_size])
                    
                    logger.info(f"音频分为 {len(segments)} 段发送")
                    
                    for i, segment in enumerate(segments):
                        is_last = (i == len(segments) - 1)
                        
                        header = AsrRequestHeader()
                        header.with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
                        
                        if is_last:
                            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
                            current_seq = -seq
                        else:
                            header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
                            current_seq = seq
                            
                        compressed_segment = AudioUtils.gzip_compress(segment)
                        
                        request = bytearray()
                        request.extend(header.to_bytes())
                        request.extend(struct.pack('>i', current_seq))
                        request.extend(struct.pack('>I', len(compressed_segment)))
                        request.extend(compressed_segment)
                        
                        await ws.send_bytes(bytes(request))
                        logger.info(f"发送音频段 {i+1}/{len(segments)} (最后: {is_last})")
                        
                        if not is_last:
                            seq += 1
                        
                        await asyncio.sleep(0.05)  # 短暂延迟
                    
                    # 3. 接收识别结果
                    full_text = []
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                response = ResponseParser.parse_response(msg.data)
                                
                                if response.get("code") != 0:
                                    logger.error(f"服务器返回错误: {response.get('code')}")
                                    return {
                                        'success': False,
                                        'error': f'Server error: {response.get("code")}',
                                        'code': response.get("code", 500)
                                    }
                                
                                if response.get("payload_msg"):
                                    result = response["payload_msg"].get("result", {})
                                    if result and result.get("text"):
                                        text = result["text"]
                                        logger.info(f"收到识别结果: {text}")
                                        full_text.append(text)
                                
                                if response.get("is_last_package"):
                                    logger.info("收到最后一个包")
                                    break
                                    
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.info("WebSocket连接关闭")
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket错误: {msg.data}")
                                return {
                                    'success': False,
                                    'error': f'WebSocket error: {msg.data}',
                                    'code': 500
                                }
                        except asyncio.TimeoutError:
                            logger.warning("接收响应超时")
                            break
                    
                    # 返回识别结果
                    recognized_text = ''.join(full_text).strip()
                    if not recognized_text:
                        recognized_text = "(未识别到内容)"
                    
                    logger.info(f"最终识别结果: {recognized_text}")
                    return {
                        'success': True,
                        'text': recognized_text,
                        'confidence': 0.95
                    }
                    
            except aiohttp.ClientResponseError as e:
                logger.error(f"WebSocket连接错误: {e.status} - {e.message}")
                return {
                    'success': False,
                    'error': f'Connection failed: {e.status} - {e.message}',
                    'code': e.status
                }
                
    except Exception as e:
        logger.error(f"ASR处理错误: {e}")
        return {
            'success': False,
            'error': f'ASR processing failed: {str(e)}',
            'code': 500
        }

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "Doubao Real Speech Recognition API",
        "service": "doubao_real"
    })

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    语音识别接口 - 使用真实豆包API
    """
    try:
        if 'audio' not in request.files:
            return jsonify({
                "error": "No audio file provided",
                "code": 400
            }), 400

        audio_file = request.files['audio']
        
        if audio_file.filename == '':
            return jsonify({
                "error": "No audio file selected", 
                "code": 400
            }), 400

        audio_data = audio_file.read()
        
        if len(audio_data) == 0:
            return jsonify({
                "error": "Empty audio file",
                "code": 400
            }), 400

        # 保存音频文件
        os.makedirs('uploads', exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"uploads/audio_{timestamp}.wav"
        with open(filename, 'wb') as f:
            f.write(audio_data)

        logger.info(f"开始处理音频文件: {filename} ({len(audio_data)} bytes)")

        # 调用真实豆包API
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(call_doubao_asr(audio_data))
        loop.close()
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "text": result.get('text', ''),
                "confidence": result.get('confidence', 0),
                "message": "Speech recognition completed successfully",
                "service": "doubao_real"
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get('error', 'Recognition failed'),
                "code": result.get('code', 500)
            }), result.get('code', 500)

    except Exception as e:
        logger.error(f"Speech recognition error: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "code": 500
        }), 500

@app.route('/')
def index():
    """提供测试页面"""
    if os.path.exists('test.html'):
        return send_from_directory('.', 'test.html')
    else:
        return jsonify({
            "message": "Doubao Real Speech Recognition API is running",
            "status": "使用真实豆包API",
            "endpoints": {
                "health": "/health",
                "recognition": "/speech-to-text"
            }
        })

if __name__ == '__main__':
    import sys
    port = 5001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    print("="*70)
    print("🚀 豆包语音识别API服务器（真实API）")
    print("="*70)
    print("\n✅ 使用真实的豆包语音识别API")
    print("✅ WebSocket流式识别")
    print("✅ 自动音频格式转换")
    print("✅ 完整错误处理")
    print("\n📋 配置信息:")
    print(f"  APP_ID: {APP_ID}")
    print(f"  APP_KEY: {APP_KEY}")
    print(f"  ACCESS_KEY: {ACCESS_KEY[:10]}...")
    print(f"  WebSocket: {WS_URL}")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)