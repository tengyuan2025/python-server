from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import io
import uuid
import os

app = Flask(__name__)
CORS(app)  # 启用CORS支持浏览器访问

# 豆包语音识别API配置
API_KEY = "35ef5232-453b-45e3-9bf7-06138ff77dc9"
# 使用火山引擎的语音识别API
ASR_URL = "https://openspeech.volcengineapi.com/api/v1/asr"

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Speech Recognition API is running"})

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    接收语音文件并使用豆包流式语音识别API进行识别
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

        # 调用豆包流式语音识别API
        result = call_doubao_asr(audio_data, audio_file.filename)
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "text": result.get('text', ''),
                "confidence": result.get('confidence', 0),
                "message": "Speech recognition completed successfully"
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

def call_doubao_asr(audio_data, filename):
    """
    调用豆包流式语音识别API
    使用multipart/form-data格式上传音频
    """
    try:
        # 生成请求ID
        request_id = str(uuid.uuid4())
        
        # 准备请求头 - 使用API Key认证
        headers = {
            'X-Api-Key': API_KEY,
            'X-Request-ID': request_id
        }
        
        # 准备文件和参数
        files = {
            'audio': ('audio.wav', audio_data, 'audio/wav')
        }
        
        # 准备表单数据
        data = {
            'language': 'zh-CN',
            'format': 'wav',
            'sample_rate': '16000',
            'enable_punctuation': 'true',
            'enable_word_time': 'false'
        }
        
        # 发送POST请求到豆包API
        response = requests.post(
            ASR_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # 解析响应结果
            if result.get('code') == 0:
                # 成功情况
                recognition_result = result.get('result', {})
                text = recognition_result.get('text', '')
                confidence = recognition_result.get('confidence', 0)
                
                return {
                    'success': True,
                    'text': text,
                    'confidence': confidence
                }
            else:
                # API返回错误
                return {
                    'success': False,
                    'error': result.get('message', 'API error'),
                    'code': result.get('code', 500)
                }
        else:
            # HTTP请求失败
            return {
                'success': False,
                'error': f'HTTP {response.status_code}: {response.text}',
                'code': response.status_code
            }
            
    except requests.RequestException as e:
        return {
            'success': False,
            'error': f'Request failed: {str(e)}',
            'code': 500
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Unexpected error: {str(e)}',
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
    port = 5001  # 改用5001端口避免与AirPlay冲突
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    
    print("="*60)
    print("🚀 语音识别API服务器启动")
    print("="*60)
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  1. 浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("  2. 运行 python record_test.py 使用命令行工具")
    print("  3. 运行 python test_client.py 测试上传音频文件")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)