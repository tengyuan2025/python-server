#!/usr/bin/env python3
"""
测试FastAPI语音处理服务
"""

import requests
import base64

def test_voice_processing():
    """测试语音处理功能"""
    # 读取测试音频文件
    with open('demo/whoareyou.wav', 'rb') as f:
        audio_data = f.read()
    
    print(f"音频文件大小: {len(audio_data)} bytes")
    
    # 测试JSON格式API
    print("\n=== 测试 JSON 格式 API ===")
    try:
        files = {'audio': ('whoareyou.wav', audio_data, 'audio/wav')}
        response = requests.post('http://localhost:8000/api/v1/process-voice-json', 
                               files=files, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                data = result['data']
                print("✅ 处理成功!")
                print(f"ASR识别文本: {data.get('asr_text', '无')}")
                print(f"对话回复: {data.get('chat_text', '无')}")
                print(f"音频格式: {data.get('audio_format')}")
                print(f"音频长度: {data.get('audio_length')} bytes")
                
                # 保存返回的音频
                if data.get('audio_data'):
                    audio_bytes = base64.b64decode(data['audio_data'])
                    with open('output_response.pcm', 'wb') as f:
                        f.write(audio_bytes)
                    print(f"✅ 输出音频已保存到 output_response.pcm")
            else:
                print(f"❌ 处理失败: {result}")
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            print(f"错误详情: {response.text}")
            
    except Exception as e:
        print(f"❌ 请求异常: {e}")

    print("\n=== 测试流式 API ===")
    try:
        files = {'audio': ('whoareyou.wav', audio_data, 'audio/wav')}
        response = requests.post('http://localhost:8000/api/v1/process-voice', 
                               files=files, timeout=60, stream=True)
        
        if response.status_code == 200:
            audio_chunks = []
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    audio_chunks.append(chunk)
            
            combined_audio = b''.join(audio_chunks)
            print(f"✅ 接收到流式音频: {len(combined_audio)} bytes")
            
            # 保存流式音频
            with open('output_stream.pcm', 'wb') as f:
                f.write(combined_audio)
            print("✅ 流式音频已保存到 output_stream.pcm")
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            
    except Exception as e:
        print(f"❌ 流式请求异常: {e}")

if __name__ == "__main__":
    test_voice_processing()