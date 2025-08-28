#!/usr/bin/env python3
"""
实时录音并测试语音识别API的脚本
支持按键录音和自动发送到API
"""
import pyaudio
import wave
import requests
import threading
import queue
import time
import os
from datetime import datetime

# API配置
API_URL = "http://localhost:5001/speech-to-text"

# 音频配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

class AudioRecorder:
    def __init__(self):
        self.recording = False
        self.frames = []
        self.audio = pyaudio.PyAudio()
        self.stream = None
        
    def start_recording(self):
        """开始录音"""
        print("\n🎤 开始录音...")
        self.recording = True
        self.frames = []
        
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        # 在新线程中录音
        def record():
            while self.recording:
                try:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                    self.frames.append(data)
                except Exception as e:
                    print(f"录音错误: {e}")
                    break
        
        threading.Thread(target=record, daemon=True).start()
        
    def stop_recording(self):
        """停止录音并保存文件"""
        if not self.recording:
            return None
            
        print("⏹️  停止录音")
        self.recording = False
        time.sleep(0.1)  # 等待录音线程结束
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        # 保存音频文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.wav"
        
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self.audio.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(self.frames))
        
        print(f"💾 音频已保存: {filename}")
        return filename
    
    def send_to_api(self, filename):
        """发送音频文件到API进行识别"""
        if not os.path.exists(filename):
            print(f"❌ 文件不存在: {filename}")
            return
        
        print(f"📤 正在发送到语音识别API...")
        
        try:
            with open(filename, 'rb') as audio_file:
                files = {'audio': audio_file}
                response = requests.post(API_URL, files=files, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        print("\n✅ 识别成功！")
                        print(f"📝 识别结果: {data.get('text', '(无内容)')}")
                        if data.get('confidence'):
                            print(f"🎯 置信度: {data.get('confidence')}")
                    else:
                        print(f"\n❌ 识别失败: {data.get('error')}")
                else:
                    print(f"\n❌ HTTP错误: {response.status_code}")
                    
        except requests.exceptions.ConnectionError:
            print("\n❌ 无法连接到API服务器，请确保服务器正在运行")
        except Exception as e:
            print(f"\n❌ 发送失败: {e}")
    
    def cleanup(self):
        """清理资源"""
        if self.stream:
            self.stream.close()
        self.audio.terminate()

def test_with_file(filepath):
    """测试已有的音频文件"""
    recorder = AudioRecorder()
    recorder.send_to_api(filepath)

def main():
    print("="*50)
    print("🎙️  语音识别测试工具")
    print("="*50)
    print("\n命令说明:")
    print("  [空格键] - 按住录音，松开停止")
    print("  [r]      - 开始/停止录音")
    print("  [f]      - 测试音频文件")
    print("  [q]      - 退出\n")
    
    recorder = AudioRecorder()
    
    try:
        # 检查API是否在线
        try:
            response = requests.get("http://localhost:5001/health", timeout=2)
            if response.status_code == 200:
                print("✅ API服务器已连接\n")
            else:
                print("⚠️  API服务器响应异常\n")
        except:
            print("⚠️  警告: 无法连接到API服务器，请确保服务器正在运行\n")
        
        while True:
            command = input("请输入命令 (r:录音, f:测试文件, q:退出): ").strip().lower()
            
            if command == 'q':
                print("\n👋 再见！")
                break
                
            elif command == 'r':
                if not recorder.recording:
                    recorder.start_recording()
                    input("按Enter键停止录音...")
                    filename = recorder.stop_recording()
                    if filename:
                        recorder.send_to_api(filename)
                        
                        # 询问是否保留文件
                        keep = input("\n是否保留录音文件? (y/n): ").strip().lower()
                        if keep != 'y':
                            os.remove(filename)
                            print(f"🗑️  已删除: {filename}")
                            
            elif command == 'f':
                filepath = input("请输入音频文件路径: ").strip()
                if os.path.exists(filepath):
                    test_with_file(filepath)
                else:
                    print(f"❌ 文件不存在: {filepath}")
                    
            else:
                print("❌ 未知命令，请输入 r, f 或 q")
                
    except KeyboardInterrupt:
        print("\n\n👋 程序已中断")
        
    finally:
        recorder.cleanup()

if __name__ == "__main__":
    # 检查是否安装了pyaudio
    try:
        import pyaudio
        main()
    except ImportError:
        print("❌ 需要安装 pyaudio 库")
        print("请运行: pip install pyaudio")
        print("\n如果安装失败，macOS用户请先安装portaudio:")
        print("  brew install portaudio")
        print("\nLinux用户请安装:")
        print("  sudo apt-get install portaudio19-dev python3-pyaudio")