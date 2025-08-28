from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import tempfile
from datetime import datetime
import speech_recognition as sr
import io
import wave

app = Flask(__name__)
CORS(app)

# 创建语音识别器
recognizer = sr.Recognizer()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Speech Recognition API is running"})

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    接收语音文件并使用本地语音识别
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

        # 保存音频文件
        os.makedirs('uploads', exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"uploads/audio_{timestamp}.wav"
        
        with open(filename, 'wb') as f:
            f.write(audio_data)

        # 调用语音识别
        result = recognize_speech(filename)
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "text": result.get('text', ''),
                "confidence": result.get('confidence', 0),
                "message": "Speech recognition completed successfully",
                "service": result.get('service', 'unknown')
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

def recognize_speech(audio_file_path):
    """
    使用多种语音识别服务尝试识别
    """
    try:
        # 使用speech_recognition库加载音频
        with sr.AudioFile(audio_file_path) as source:
            audio = recognizer.record(source)
        
        # 尝试不同的识别服务
        results = []
        
        # 1. 尝试Google语音识别（免费，无需API密钥）
        try:
            text = recognizer.recognize_google(audio, language='zh-CN')
            return {
                'success': True,
                'text': text,
                'confidence': 0.9,
                'service': 'google'
            }
        except sr.UnknownValueError:
            results.append("Google语音识别无法理解音频")
        except sr.RequestError as e:
            results.append(f"Google服务错误: {e}")
        
        # 2. 尝试Whisper API（如果可用）
        try:
            text = recognizer.recognize_whisper_api(
                audio,
                api_key=os.getenv('OPENAI_API_KEY', '')
            )
            return {
                'success': True,
                'text': text,
                'confidence': 0.95,
                'service': 'whisper'
            }
        except:
            results.append("Whisper API不可用")
        
        # 3. 如果都失败了，返回错误信息
        return {
            'success': False,
            'error': '无法识别音频内容。尝试过的服务: ' + '; '.join(results),
            'code': 500
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'识别过程出错: {str(e)}',
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
    print("🚀 语音识别API服务器启动（Google/Whisper版）")
    print("="*60)
    print("\n📝 特点:")
    print("  ✅ 使用Google免费语音识别API（无需密钥）")
    print("  ✅ 支持中文识别")
    print("  ✅ 如配置OPENAI_API_KEY环境变量，可使用Whisper")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)