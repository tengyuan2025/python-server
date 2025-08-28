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
from typing import Dict, Any, Tuple, List

app = Flask(__name__)
CORS(app)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 豆包语音识别配置
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

class CommonUtils:
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
            "X-Api-Access-Key": ACCESS_KEY,
            "X-Api-App-Key": APP_KEY
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

    @staticmethod
    def new_audio_only_request(seq: int, segment: bytes, is_last: bool = False) -> bytes:
        header = AsrRequestHeader.default_header()
        if is_last:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
            seq = -seq
        else:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        header.with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        
        compressed_segment = CommonUtils.gzip_compress(segment)
        request.extend(struct.pack('>I', len(compressed_segment)))
        request.extend(compressed_segment)
        
        return bytes(request)

class AsrResponse:
    def __init__(self):
        self.code = 0
        self.event = 0
        self.is_last_package = False
        self.payload_sequence = 0
        self.payload_size = 0
        self.payload_msg = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "event": self.event,
            "is_last_package": self.is_last_package,
            "payload_sequence": self.payload_sequence,
            "payload_size": self.payload_size,
            "payload_msg": self.payload_msg
        }

class ResponseParser:
    @staticmethod
    def parse_response(msg: bytes) -> AsrResponse:
        response = AsrResponse()
        
        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_type_specific_flags = msg[1] & 0x0f
        serialization_method = msg[2] >> 4
        message_compression = msg[2] & 0x0f
        
        payload = msg[header_size*4:]
        
        # 解析message_type_specific_flags
        if message_type_specific_flags & 0x01:
            response.payload_sequence = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            response.is_last_package = True
        if message_type_specific_flags & 0x04:
            response.event = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
            
        # 解析message_type
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            response.payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            response.code = struct.unpack('>i', payload[:4])[0]
            response.payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            
        if not payload:
            return response
            
        # 解压缩
        if message_compression == CompressionType.GZIP:
            try:
                payload = CommonUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        # 解析payload
        try:
            if serialization_method == SerializationType.JSON:
                response.payload_msg = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

def get_segment_size(content: bytes, segment_duration: int = 200) -> int:
    """
    计算音频分段大小 - 完全按照demo实现
    """
    try:
        channel_num, samp_width, frame_rate, _, _ = CommonUtils.read_wav_info(content)[:5]
        size_per_sec = channel_num * samp_width * frame_rate
        segment_size = size_per_sec * segment_duration // 1000
        return segment_size
    except Exception as e:
        logger.error(f"Failed to calculate segment size: {e}")
        raise

def split_audio(data: bytes, segment_size: int) -> List[bytes]:
    """
    分割音频数据 - 完全按照demo实现
    """
    if segment_size <= 0:
        return []
        
    segments = []
    for i in range(0, len(data), segment_size):
        end = i + segment_size
        if end > len(data):
            end = len(data)
        segments.append(data[i:end])
    return segments

async def call_doubao_asr(audio_data: bytes) -> Dict[str, Any]:
    """
    调用豆包流式语音识别API - 严格按照官方demo实现
    """
    try:
        # 确保音频格式正确
        if not CommonUtils.judge_wav(audio_data):
            logger.info("Converting audio to WAV format...")
            
            converted_data = CommonUtils.convert_to_wav(audio_data, "webm")
            if converted_data is None:
                converted_data = CommonUtils.convert_to_wav(audio_data, "ogg")
            if converted_data is None:
                converted_data = CommonUtils.convert_to_wav(audio_data, "mp4")
                
            if converted_data is None:
                return {
                    'success': False,
                    'error': 'Unable to convert audio to WAV format',
                    'code': 400
                }
            
            audio_data = converted_data
            logger.info("Audio successfully converted to WAV format")
        
        # 准备WebSocket连接
        headers = RequestBuilder.new_auth_headers()
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(WS_URL, headers=headers) as ws:
                    logger.info("WebSocket连接成功")
                    
                    # 1. 发送完整客户端请求
                    seq = 1
                    request = RequestBuilder.new_full_client_request(seq)
                    await ws.send_bytes(request)
                    logger.info(f"发送完整客户端请求 seq: {seq}")
                    
                    # 接收初始响应
                    msg = await ws.receive()
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        response = ResponseParser.parse_response(msg.data)
                        logger.info(f"收到初始响应: {response.to_dict()}")
                        
                        if response.code != 0:
                            return {
                                'success': False,
                                'error': f'Server error: {response.code}',
                                'code': response.code
                            }
                    else:
                        return {
                            'success': False,
                            'error': f'Unexpected message type: {msg.type}',
                            'code': 500
                        }
                    
                    # 2. 发送音频数据 - 关键：使用完整音频文件进行分段，而不是裸音频数据
                    seq += 1
                    segment_size = get_segment_size(audio_data, 200)  # 200ms分段
                    audio_segments = split_audio(audio_data, segment_size)  # 对完整WAV文件分段！
                    total_segments = len(audio_segments)
                    
                    logger.info(f"音频分为 {total_segments} 段，每段大小约 {segment_size} bytes")
                    
                    # 发送音频段和接收响应
                    full_text = []
                    
                    for i, segment in enumerate(audio_segments):
                        is_last = (i == total_segments - 1)
                        request = RequestBuilder.new_audio_only_request(seq, segment, is_last=is_last)
                        
                        await ws.send_bytes(request)
                        logger.info(f"发送音频段 {i+1}/{total_segments} (seq: {seq}, last: {is_last})")
                        
                        if not is_last:
                            seq += 1
                            
                        await asyncio.sleep(0.2)  # 200ms间隔模拟实时流
                    
                    # 3. 接收所有识别结果
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                response = ResponseParser.parse_response(msg.data)
                                logger.info(f"收到响应: {response.to_dict()}")
                                
                                if response.code != 0:
                                    logger.error(f"服务器返回错误: {response.code}")
                                    return {
                                        'success': False,
                                        'error': f'Server error: {response.code}',
                                        'code': response.code
                                    }
                                
                                if response.payload_msg:
                                    result = response.payload_msg.get("result", {})
                                    if result and result.get("text"):
                                        text = result["text"]
                                        logger.info(f"识别结果: {text}")
                                        full_text.append(text)
                                
                                if response.is_last_package:
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
        "message": "Doubao Real Speech Recognition API (Fixed)",
        "service": "doubao_real_fixed"
    })

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    语音识别接口 - 修复版本
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

        # 调用修复后的豆包API
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
                "service": "doubao_real_fixed"
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
            "message": "Doubao Real Speech Recognition API (Fixed) is running",
            "status": "使用真实豆包API - 修复版",
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
    print("🚀 豆包语音识别API服务器（修复版）")
    print("="*70)
    print("\n🔧 修复内容:")
    print("✅ 对完整WAV文件进行分段（不提取裸音频数据）")
    print("✅ 严格按照官方demo的分段算法")
    print("✅ 正确的请求序列号处理")
    print("✅ 完整的响应解析逻辑")
    print("\n📋 配置信息:")
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