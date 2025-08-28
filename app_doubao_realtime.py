from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
import os
import base64
import threading
from datetime import datetime
from typing import Dict, Any, Optional
import queue

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 豆包语音识别配置
APP_KEY = "7059594059"
ACCESS_KEY = "tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt"

# WebSocket URL
WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"  # 使用实时流式版本

# 存储实时连接
active_connections = {}

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
            "X-Api-Access-Key": ACCESS_KEY,
            "X-Api-App-Key": APP_KEY
        }

    @staticmethod
    def new_full_client_request(seq: int) -> bytes:
        header = AsrRequestHeader.default_header().with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        
        payload = {
            "user": {
                "uid": "realtime_client"
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
                "enable_nonstream": True,  # 启用实时流式识别
                "partial_result": True      # 返回部分结果
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

class ResponseParser:
    @staticmethod
    def parse_response(msg: bytes) -> Dict[str, Any]:
        response = {
            "code": 0,
            "is_last_package": False,
            "payload_msg": None,
            "event": 0
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
        if message_type_specific_flags & 0x04:
            response["event"] = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
            
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
                payload = CommonUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        try:
            if serialization_method == SerializationType.JSON:
                response["payload_msg"] = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

class RealTimeAsrConnection:
    def __init__(self, session_id: str, client_emit):
        self.session_id = session_id
        self.client_emit = client_emit
        self.ws = None
        self.session = None
        self.seq = 1
        self.audio_queue = queue.Queue()
        self.is_connected = False
        self.is_recording = False
        
    async def connect(self):
        """建立到豆包API的WebSocket连接"""
        try:
            headers = RequestBuilder.new_auth_headers()
            self.session = aiohttp.ClientSession()
            self.ws = await self.session.ws_connect(WS_URL, headers=headers)
            self.is_connected = True
            
            logger.info(f"Session {self.session_id}: 连接到豆包API成功")
            
            # 发送初始请求
            request = RequestBuilder.new_full_client_request(self.seq)
            await self.ws.send_bytes(request)
            self.seq += 1
            
            # 启动响应监听
            asyncio.create_task(self.listen_responses())
            
            return True
            
        except Exception as e:
            logger.error(f"Session {self.session_id}: 连接失败 {e}")
            await self.cleanup()
            return False
    
    async def listen_responses(self):
        """监听豆包API的响应"""
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    response = ResponseParser.parse_response(msg.data)
                    
                    if response.get("code") != 0:
                        logger.error(f"Session {self.session_id}: 服务器错误 {response.get('code')}")
                        self.client_emit('asr_error', {
                            'error': f'Server error: {response.get("code")}',
                            'code': response.get("code")
                        })
                        continue
                    
                    if response.get("payload_msg"):
                        result = response["payload_msg"].get("result", {})
                        if result:
                            # 发送实时识别结果到前端
                            self.client_emit('asr_result', {
                                'text': result.get("text", ""),
                                'is_final': response.get("is_last_package", False),
                                'confidence': result.get("confidence", 0)
                            })
                            
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Session {self.session_id}: WebSocket错误")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Session {self.session_id}: WebSocket连接关闭")
                    break
                    
        except Exception as e:
            logger.error(f"Session {self.session_id}: 监听响应错误 {e}")
        finally:
            await self.cleanup()
    
    async def send_audio_chunk(self, audio_data: bytes, is_last: bool = False):
        """发送音频数据块"""
        if not self.is_connected or not self.ws:
            return False
            
        try:
            request = RequestBuilder.new_audio_only_request(self.seq, audio_data, is_last)
            await self.ws.send_bytes(request)
            
            if not is_last:
                self.seq += 1
                
            return True
            
        except Exception as e:
            logger.error(f"Session {self.session_id}: 发送音频失败 {e}")
            return False
    
    async def cleanup(self):
        """清理连接"""
        self.is_connected = False
        self.is_recording = False
        
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()
            
        logger.info(f"Session {self.session_id}: 连接已清理")

# SocketIO 事件处理
@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"Client {session_id} connected")
    emit('connected', {'session_id': session_id})

@socketio.on('disconnect') 
def handle_disconnect():
    session_id = request.sid
    logger.info(f"Client {session_id} disconnected")
    
    # 清理连接
    if session_id in active_connections:
        connection = active_connections[session_id]
        asyncio.run(connection.cleanup())
        del active_connections[session_id]

@socketio.on('start_realtime_asr')
def handle_start_realtime_asr():
    """开始实时语音识别"""
    session_id = request.sid
    
    def client_emit(event, data):
        socketio.emit(event, data, room=session_id)
    
    # 创建新的连接
    connection = RealTimeAsrConnection(session_id, client_emit)
    active_connections[session_id] = connection
    
    # 在新线程中建立连接
    def connect_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(connection.connect())
        loop.close()
        
        if success:
            socketio.emit('asr_ready', {'status': 'ready'}, room=session_id)
        else:
            socketio.emit('asr_error', {'error': 'Failed to connect'}, room=session_id)
    
    threading.Thread(target=connect_async, daemon=True).start()
    logger.info(f"Session {session_id}: 启动实时语音识别")

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """处理实时音频数据块"""
    session_id = request.sid
    
    if session_id not in active_connections:
        emit('asr_error', {'error': 'No active connection'})
        return
    
    connection = active_connections[session_id]
    
    try:
        # 解码base64音频数据
        audio_data = base64.b64decode(data['audio'])
        is_last = data.get('is_last', False)
        
        # 在新线程中发送音频
        def send_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(connection.send_audio_chunk(audio_data, is_last))
            loop.close()
        
        threading.Thread(target=send_async, daemon=True).start()
        
    except Exception as e:
        logger.error(f"Session {session_id}: 处理音频块失败 {e}")
        emit('asr_error', {'error': str(e)})

@socketio.on('stop_realtime_asr')
def handle_stop_realtime_asr():
    """停止实时语音识别"""
    session_id = request.sid
    
    if session_id in active_connections:
        connection = active_connections[session_id] 
        
        def cleanup_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(connection.cleanup())
            loop.close()
        
        threading.Thread(target=cleanup_async, daemon=True).start()
        del active_connections[session_id]
    
    emit('asr_stopped', {'status': 'stopped'})
    logger.info(f"Session {session_id}: 停止实时语音识别")

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "Doubao Realtime Speech Recognition API",
        "service": "doubao_realtime"
    })

@app.route('/')
def index():
    """提供实时语音识别测试页面"""
    if os.path.exists('realtime_test.html'):
        return send_from_directory('.', 'realtime_test.html')
    else:
        return jsonify({
            "message": "Doubao Realtime Speech Recognition API is running",
            "status": "实时语音识别服务",
            "endpoints": {
                "health": "/health",
                "websocket": "/socket.io/"
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
    print("🚀 豆包实时语音识别API服务器")
    print("="*70)
    print("\n🎤 实时语音识别功能:")
    print("✅ 实时音频流传输")
    print("✅ 实时识别结果返回") 
    print("✅ WebSocket双向通信")
    print("✅ 支持中断词和部分结果")
    print("\n📋 配置信息:")
    print(f"  APP_KEY: {APP_KEY}")
    print(f"  ACCESS_KEY: {ACCESS_KEY[:10]}...")
    print(f"  WebSocket: {WS_URL}")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  WebSocket: http://localhost:{port}/socket.io/")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  浏览器访问 http://localhost:{port}/ 使用实时语音识别")
    print("\n按 Ctrl+C 停止服务器\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)