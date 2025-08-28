#!/usr/bin/env python3
"""
测试语音识别API的客户端脚本
"""
import requests
import os

def test_speech_recognition(audio_file_path, server_url="http://localhost:5001"):
    """
    测试语音识别API
    """
    if not os.path.exists(audio_file_path):
        print(f"错误: 音频文件 {audio_file_path} 不存在")
        return
    
    # 健康检查
    try:
        health_response = requests.get(f"{server_url}/health")
        print(f"健康检查: {health_response.json()}")
    except Exception as e:
        print(f"健康检查失败: {e}")
        return
    
    # 发送音频文件进行识别
    try:
        with open(audio_file_path, 'rb') as audio_file:
            files = {'audio': audio_file}
            response = requests.post(f"{server_url}/speech-to-text", files=files)
            
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.json()}")
            
    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    # 使用示例
    # test_speech_recognition("path/to/your/audio/file.wav")
    print("使用方法: test_speech_recognition('your_audio_file.wav')")
    print("请先启动服务器: python app.py")