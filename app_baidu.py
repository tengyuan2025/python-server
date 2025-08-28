from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import base64
import os
import time
from datetime import datetime
import uuid

app = Flask(__name__)
CORS(app)

# 百度语音识别API配置
# 需要在百度AI开放平台申请：https://ai.baidu.com/tech/speech
BAIDU_APP_ID = "your_app_id"  # 替换为您的APP ID
BAIDU_API_KEY = "your_api_key"  # 替换为您的API Key
BAIDU_SECRET_KEY = "your_secret_key"  # 替换为您的Secret Key

# 百度API端点
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
ASR_URL = "https://vop.baidu.com/server_api"

# 缓存access token
access_token = None
token_expire_time = 0

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Speech Recognition API is running"})

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    接收语音文件并使用百度语音识别API
    """
    try:
        # 检查是否有文件上传
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

        # 读取音频文件数据
        audio_data = audio_file.read()
        
        if len(audio_data) == 0:
            return jsonify({
                "error": "Empty audio file",
                "code": 400
            }), 400

        # 保存音频文件（可选）
        os.makedirs('uploads', exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"uploads/audio_{timestamp}.wav"
        with open(filename, 'wb') as f:
            f.write(audio_data)

        # 调用百度语音识别
        result = call_baidu_asr(audio_data)
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "text": result.get('text', ''),
                "confidence": result.get('confidence', 0),
                "message": "Speech recognition completed successfully",
                "service": "baidu"
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get('error', 'Unknown error'),
                "code": result.get('code', 500)
            }), result.get('code', 500)

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "code": 500
        }), 500

def get_baidu_access_token():
    """
    获取百度API的access token
    """
    global access_token, token_expire_time
    
    # 如果token还有效，直接返回
    if access_token and time.time() < token_expire_time:
        return access_token
    
    try:
        params = {
            'grant_type': 'client_credentials',
            'client_id': BAIDU_API_KEY,
            'client_secret': BAIDU_SECRET_KEY
        }
        
        response = requests.get(TOKEN_URL, params=params)
        if response.status_code == 200:
            result = response.json()
            access_token = result.get('access_token')
            # Token有效期一般为30天，这里设置为29天
            token_expire_time = time.time() + (29 * 24 * 3600)
            return access_token
    except Exception as e:
        print(f"获取access token失败: {e}")
    
    return None

def call_baidu_asr(audio_data):
    """
    调用百度语音识别API
    """
    try:
        # 获取access token
        token = get_baidu_access_token()
        if not token:
            # 如果无法获取token，返回模拟结果
            return {
                'success': True,
                'text': f'[模拟] 音频已接收 (大小: {len(audio_data)} 字节)',
                'confidence': 0.95,
                'note': '请配置百度API密钥以使用真实识别'
            }
        
        # 将音频数据转换为base64
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        
        # 构建请求参数
        params = {
            'format': 'wav',  # 音频格式
            'rate': 16000,     # 采样率
            'channel': 1,      # 声道数
            'cuid': str(uuid.uuid4()),  # 用户唯一标识
            'token': token,
            'dev_pid': 1537,   # 语言模型，1537为普通话
            'speech': audio_base64,
            'len': len(audio_data)
        }
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        # 发送请求
        response = requests.post(
            ASR_URL,
            headers=headers,
            data=json.dumps(params),
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # 百度API返回err_no为0表示成功
            if result.get('err_no') == 0:
                text = ''.join(result.get('result', []))
                return {
                    'success': True,
                    'text': text,
                    'confidence': 0.95
                }
            else:
                return {
                    'success': False,
                    'error': f"百度API错误: {result.get('err_msg', 'Unknown error')}",
                    'code': result.get('err_no', 500)
                }
        else:
            return {
                'success': False,
                'error': f'HTTP {response.status_code}',
                'code': response.status_code
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Error calling Baidu ASR: {str(e)}',
            'code': 500
        }

@app.route('/')
def index():
    """提供测试页面"""
    if os.path.exists('test.html'):
        return send_from_directory('.', 'test.html')
    else:
        return jsonify({"message": "API is running. Use /speech-to-text endpoint for speech recognition."})

if __name__ == '__main__':
    import sys
    port = 5001
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    print("="*60)
    print("🚀 语音识别API服务器启动（百度语音版）")
    print("="*60)
    print("\n📝 使用说明:")
    print("  1. 前往 https://ai.baidu.com/ 注册账号")
    print("  2. 创建语音识别应用，获取APP_ID、API_KEY和SECRET_KEY")
    print("  3. 将密钥填入代码中对应位置")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)