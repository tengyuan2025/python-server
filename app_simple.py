from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import base64
import hashlib
from datetime import datetime

app = Flask(__name__)
CORS(app)

# API配置
API_KEY = "35ef5232-453b-45e3-9bf7-06138ff77dc9"

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Speech Recognition API is running"})

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    接收语音文件的简化版本 - 用于测试
    实际使用时需要替换为真实的豆包API调用
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"uploads/audio_{timestamp}.wav"
        os.makedirs('uploads', exist_ok=True)
        
        with open(filename, 'wb') as f:
            f.write(audio_data)
        
        # 模拟返回结果（实际使用时替换为真实API调用）
        # 这里可以根据音频文件大小返回不同的模拟文本
        file_size = len(audio_data)
        
        if file_size < 10000:
            mock_text = "测试语音识别成功"
        elif file_size < 50000:
            mock_text = "这是一段较长的语音识别测试结果"
        else:
            mock_text = "您上传了一个较大的音频文件，语音识别功能正常工作"
        
        # 返回模拟结果
        return jsonify({
            "success": True,
            "text": mock_text,
            "confidence": 0.95,
            "message": "Speech recognition completed successfully",
            "debug": {
                "file_size": file_size,
                "filename": filename,
                "note": "这是模拟结果，请替换为真实的豆包API调用"
            }
        })

    except Exception as e:
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
    print("🚀 语音识别API服务器启动（简化测试版）")
    print("="*60)
    print("\n⚠️  注意：当前使用模拟响应，请根据豆包API文档更新实现")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  1. 浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("  2. 运行 python record_test.py 使用命令行工具")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)