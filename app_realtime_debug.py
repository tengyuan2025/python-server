from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import base64
import logging
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 存储会话信息
sessions = {}

@socketio.on('connect')
def handle_connect():
    session_id = request.sid
    logger.info(f"🔗 Client {session_id} connected")
    sessions[session_id] = {
        'connected': True,
        'recording': False,
        'chunk_count': 0
    }
    emit('connected', {'session_id': session_id, 'status': 'connected'})

@socketio.on('disconnect') 
def handle_disconnect():
    session_id = request.sid
    logger.info(f"❌ Client {session_id} disconnected")
    if session_id in sessions:
        del sessions[session_id]

@socketio.on('start_realtime_asr')
def handle_start_realtime_asr():
    """开始实时语音识别 - 调试版"""
    session_id = request.sid
    logger.info(f"🎤 Session {session_id}: 启动实时语音识别")
    
    if session_id in sessions:
        sessions[session_id]['recording'] = True
        sessions[session_id]['chunk_count'] = 0
        
        # 模拟连接成功
        emit('asr_ready', {'status': 'ready', 'message': '语音识别已就绪'})
        logger.info(f"✅ Session {session_id}: ASR ready emitted")
    else:
        emit('asr_error', {'error': 'Session not found'})

@socketio.on('audio_chunk')
def handle_audio_chunk(data):
    """处理实时音频数据块 - 调试版"""
    session_id = request.sid
    
    if session_id not in sessions:
        emit('asr_error', {'error': 'No active session'})
        return
    
    session_info = sessions[session_id]
    session_info['chunk_count'] += 1
    
    try:
        # 解码音频数据
        if 'audio' in data and data['audio']:
            audio_data = base64.b64decode(data['audio'])
            audio_size = len(audio_data)
            is_last = data.get('is_last', False)
            
            logger.info(f"🎵 Session {session_id}: 收到音频块 #{session_info['chunk_count']} "
                       f"(大小: {audio_size} bytes, 最后: {is_last})")
            
            # 模拟识别结果
            if session_info['chunk_count'] % 3 == 0:  # 每3个块返回一次部分结果
                mock_text = f"测试识别结果 {session_info['chunk_count']//3}"
                emit('asr_result', {
                    'text': mock_text,
                    'is_final': False,
                    'confidence': 0.85
                })
                logger.info(f"📝 Session {session_id}: 发送部分结果: {mock_text}")
            
            if is_last:
                final_text = f"最终识别结果，共处理 {session_info['chunk_count']} 个音频块"
                emit('asr_result', {
                    'text': final_text,
                    'is_final': True,
                    'confidence': 0.95
                })
                logger.info(f"✅ Session {session_id}: 发送最终结果: {final_text}")
        else:
            logger.warning(f"⚠️ Session {session_id}: 空音频数据")
            
    except Exception as e:
        logger.error(f"❌ Session {session_id}: 处理音频块失败: {e}")
        emit('asr_error', {'error': f'Audio processing failed: {str(e)}'})

@socketio.on('stop_realtime_asr')
def handle_stop_realtime_asr():
    """停止实时语音识别"""
    session_id = request.sid
    logger.info(f"🛑 Session {session_id}: 停止实时语音识别")
    
    if session_id in sessions:
        sessions[session_id]['recording'] = False
        emit('asr_stopped', {'status': 'stopped', 'message': '语音识别已停止'})
    else:
        emit('asr_error', {'error': 'Session not found'})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "Realtime ASR Debug Server",
        "active_sessions": len(sessions)
    })

@app.route('/')
def index():
    """提供调试测试页面"""
    if os.path.exists('realtime_test.html'):
        return send_from_directory('.', 'realtime_test.html')
    else:
        return jsonify({
            "message": "Realtime ASR Debug Server is running",
            "active_sessions": len(sessions)
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
    print("🐛 实时语音识别调试服务器")
    print("="*70)
    print("\n🔍 调试功能:")
    print("✅ 详细的连接和音频处理日志")
    print("✅ 模拟识别结果（不调用真实API）")
    print("✅ WebSocket通信状态监控")
    print("✅ 音频数据接收验证")
    print("\n📍 服务端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  WebSocket: http://localhost:{port}/socket.io/")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 使用方式:")
    print(f"  1. 浏览器访问 http://localhost:{port}/")
    print("  2. 打开浏览器开发者工具查看详细日志")
    print("  3. 点击开始录音，查看服务器日志输出")
    print("\n🔧 调试步骤:")
    print("  1. 检查WebSocket连接是否成功")
    print("  2. 检查音频权限是否获取")
    print("  3. 检查音频数据是否正常发送")
    print("  4. 检查服务器是否收到数据")
    print("\n按 Ctrl+C 停止服务器\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)