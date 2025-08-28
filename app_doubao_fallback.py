from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import tempfile
from datetime import datetime
import logging
import subprocess

app = Flask(__name__)
CORS(app)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 豆包API配置（当前认证失败）
APP_KEY = "35ef5232-453b-45e3-9bf7-06138ff77dc9"
ACCESS_KEY = "35ef5232-453b-45e3-9bf7-06138ff77dc9"
APP_ID = "7059594059"

class AudioUtils:
    @staticmethod
    def judge_wav(data: bytes) -> bool:
        if len(data) < 44:
            return False
        return data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    
    @staticmethod
    def convert_to_wav(audio_data: bytes, input_format: str = "webm") -> bytes:
        """
        将音频数据转换为WAV格式
        """
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

def analyze_audio(audio_data: bytes) -> dict:
    """
    分析音频并返回模拟识别结果
    """
    try:
        # 保存音频文件用于分析
        os.makedirs('uploads', exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"uploads/audio_{timestamp}.wav"
        
        # 确保是WAV格式
        if not AudioUtils.judge_wav(audio_data):
            logger.info("Converting audio to WAV format...")
            wav_data = AudioUtils.convert_to_wav(audio_data, "webm")
            if wav_data is None:
                wav_data = AudioUtils.convert_to_wav(audio_data, "ogg")
            if wav_data is None:
                wav_data = AudioUtils.convert_to_wav(audio_data, "mp4")
            if wav_data:
                audio_data = wav_data
            else:
                logger.warning("Failed to convert audio, using original data")
        
        with open(filename, 'wb') as f:
            f.write(audio_data)
        
        # 分析音频特征来生成更真实的模拟结果
        audio_size = len(audio_data)
        
        # 根据音频大小判断可能的内容长度
        if audio_size < 50000:  # 小于50KB，可能是短语
            mock_results = [
                "你好",
                "谢谢",
                "再见",
                "测试成功",
                "语音识别",
                "人工智能"
            ]
        elif audio_size < 200000:  # 50KB-200KB，中等长度
            mock_results = [
                "今天天气怎么样",
                "请帮我查询一下信息",
                "这是一个语音识别测试",
                "人工智能技术正在快速发展",
                "我想了解更多关于这个产品的信息"
            ]
        else:  # 大于200KB，较长内容
            mock_results = [
                "这是一段较长的语音内容，展示了语音识别技术的强大能力",
                "随着人工智能技术的不断发展，语音识别已经成为了我们日常生活中不可或缺的一部分",
                "通过深度学习和神经网络技术，现代语音识别系统能够准确理解人类的语言"
            ]
        
        # 根据时间选择不同的结果（增加随机性）
        import hashlib
        audio_hash = hashlib.md5(audio_data).hexdigest()
        result_index = int(audio_hash[-1], 16) % len(mock_results)
        
        return {
            'success': True,
            'text': mock_results[result_index],
            'confidence': 0.92,
            'note': '模拟识别结果 - 豆包API认证失败',
            'audio_info': {
                'size': audio_size,
                'saved_to': filename,
                'format': 'WAV' if AudioUtils.judge_wav(audio_data) else 'Converted to WAV'
            }
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Audio analysis failed: {str(e)}',
            'code': 500
        }

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy", 
        "message": "Doubao Speech Recognition API (Fallback Mode)",
        "note": "API认证失败，当前使用模拟识别"
    })

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    接收语音文件并返回识别结果（当前使用模拟数据）
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

        # 分析音频并返回模拟结果
        result = analyze_audio(audio_data)
        
        if result.get('success'):
            return jsonify({
                "success": True,
                "text": result.get('text', ''),
                "confidence": result.get('confidence', 0),
                "message": "Speech recognition completed (simulated)",
                "service": "doubao_fallback",
                "note": result.get('note', ''),
                "debug": result.get('audio_info', {})
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

@app.route('/')
def index():
    """提供测试页面和配置说明"""
    if os.path.exists('test.html'):
        return send_from_directory('.', 'test.html')
    else:
        return jsonify({
            "message": "API is running in fallback mode",
            "status": "豆包API认证失败，使用模拟识别",
            "help": "请参考启动信息获取正确的API密钥"
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
    print("🚀 豆包语音识别API服务器（回退模式）")
    print("="*70)
    print("\n⚠️  API认证失败 - 使用模拟识别")
    print("\n🔑 如需使用真实豆包API，请完成以下步骤：")
    print("1. 登录火山引擎控制台：https://console.volcengine.com/")
    print("2. 进入【语音技术】->【语音识别】服务")
    print("3. 创建应用或查看现有应用")
    print("4. 获取正确的 APP_KEY 和 ACCESS_KEY")
    print("5. 确保应用已开通语音识别权限")
    print("6. 在代码中替换密钥配置")
    print("\n📋 当前配置:")
    print(f"  APP_ID: {APP_ID}")
    print(f"  APP_KEY: {APP_KEY}")
    print(f"  ACCESS_KEY: {ACCESS_KEY}")
    print("\n📍 API端点:")
    print(f"  健康检查: http://localhost:{port}/health")
    print(f"  语音识别: http://localhost:{port}/speech-to-text")
    print(f"  测试界面: http://localhost:{port}/")
    print("\n💡 测试方式:")
    print(f"  浏览器访问 http://localhost:{port}/ 使用网页界面")
    print("  当前会返回基于音频特征的模拟识别结果")
    print("\n按 Ctrl+C 停止服务器\n")
    app.run(host='0.0.0.0', port=port, debug=True)