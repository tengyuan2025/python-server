#!/usr/bin/env python3
"""
基于FastAPI的语音处理服务
接收客户端语音文件，转发给豆包实时语音API，并返回处理结果
"""

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import uuid
import io
import json
import logging
from typing import Dict, Any, AsyncIterator
import websockets
import gzip

# 导入demo中的模块
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'demo'))

try:
    import protocol
    from realtime_dialog_client import RealtimeDialogClient
except ImportError as e:
    logging.error(f"导入demo模块失败: {e}")
    logging.error("请确保demo文件夹存在且包含protocol.py和realtime_dialog_client.py")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title="豆包语音处理服务",
    description="接收客户端语音文件，通过豆包实时语音API处理并返回结果",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 豆包API配置
DOUBAO_CONFIG = {
    'base_url': 'wss://openspeech.bytedance.com/api/v3/realtime/dialogue',
    'headers': {
        'X-Api-App-ID': '7059594059',
        'X-Api-Access-Key': 'tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt',
        'X-Api-Resource-Id': 'volc.speech.dialog',
        'X-Api-App-Key': 'PlgvMymc7f3tQnJ6',
        'X-Api-Connect-Id': str(uuid.uuid4()),
    }
}

# 会话配置
START_SESSION_CONFIG = {
    "asr": {
        "extra": {
            "end_smooth_window_ms": 1500,
        },
    },
    "tts": {
        "speaker": "zh_female_vv_jupiter_bigtts",
        "audio_config": {
            "channel": 1,
            "format": "pcm_s16le",  # 使用16位PCM格式便于处理
            "sample_rate": 24000
        },
    },
    "dialog": {
        "bot_name": "豆包",
        "system_role": "你是一个智能语音助手，能够理解用户的语音并给出恰当的回复。",
        "speaking_style": "你的说话风格自然流畅，语调亲切。",
        "extra": {
            "strict_audit": False,
        }
    }
}


class VoiceProcessor:
    """语音处理器 - 基于demo中的DialogSession实现"""
    
    def __init__(self):
        self.client = None
        self.session_id = str(uuid.uuid4())
        self.audio_chunks = []
        self.is_processing = False
        self.is_session_finished = False
        
    async def connect_to_doubao(self):
        """连接到豆包API"""
        try:
            self.client = RealtimeDialogClient(
                config=DOUBAO_CONFIG,
                session_id=self.session_id,
                output_audio_format="pcm_s16le"
            )
            await self.client.connect()
            logger.info(f"成功连接到豆包API, session_id: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"连接豆包API失败: {e}")
            return False
    
    def handle_server_response(self, response: Dict[str, Any]) -> bytes:
        """处理服务器响应 - 参考demo中的实现"""
        if response == {}:
            return None
            
        # 处理音频数据响应
        if response['message_type'] == 'SERVER_ACK' and isinstance(response.get('payload_msg'), bytes):
            audio_data = response['payload_msg']
            logger.debug(f"接收到音频数据: {len(audio_data)} bytes")
            self.audio_chunks.append(audio_data)
            return audio_data
            
        # 处理完整响应
        elif response['message_type'] == 'SERVER_FULL_RESPONSE':
            event = response.get('event')
            payload_msg = response.get('payload_msg', {})
            
            logger.info(f"服务器事件: {event}, payload: {payload_msg}")
            
            if event == 450:  # ASRInfo - 用户开始说话
                logger.info("检测到用户开始说话")
                
            elif event == 451:  # ASRResponse - 语音识别结果
                if 'results' in payload_msg and payload_msg['results']:
                    asr_text = payload_msg['results'][0].get('text', '')
                    logger.info(f"ASR识别结果: {asr_text}")
                    
            elif event == 459:  # ASREnded - 用户说话结束
                logger.info("用户说话结束")
                
            elif event == 350:  # TTSSentenceStart - TTS开始
                logger.info("TTS合成开始")
                
            elif event == 352:  # TTSResponse - 在SERVER_ACK中处理
                pass
                
            elif event == 359:  # TTSEnded - TTS结束
                logger.info("TTS合成结束")
                self.is_processing = False
                
            elif event == 550:  # ChatResponse - 对话回复
                chat_content = payload_msg.get('content', '')
                logger.info(f"对话回复: {chat_content}")
                
            elif event in [152, 153]:  # SessionFinished/SessionFailed
                logger.info(f"会话结束: {event}")
                self.is_session_finished = True
                self.is_processing = False
                
        elif response['message_type'] == 'SERVER_ERROR':
            error_msg = response.get('payload_msg', 'Unknown error')
            logger.error(f"服务器错误: {error_msg}")
            raise Exception(f"服务器错误: {error_msg}")
            
        return None
    
    async def process_audio_file(self, audio_data: bytes) -> AsyncIterator[bytes]:
        """处理音频文件 - 参考demo中的process_audio_file_input"""
        if not self.client:
            if not await self.connect_to_doubao():
                raise Exception("无法连接到豆包API")
        
        try:
            self.is_processing = True
            self.audio_chunks = []
            
            logger.info(f"开始处理音频数据，长度: {len(audio_data)} bytes")
            
            # 按chunk分块发送音频数据（参考demo实现）
            chunk_size = 3200  # 与demo中的配置一致
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                if chunk:
                    await self.client.task_request(chunk)
                    logger.debug(f"发送音频块: {len(chunk)} bytes")
            
            logger.info("音频数据发送完成，开始接收响应...")
            
            # 启动接收循环
            while self.is_processing and not self.is_session_finished:
                try:
                    response = await asyncio.wait_for(
                        self.client.receive_server_response(),
                        timeout=10.0
                    )
                    
                    # 处理响应并获取音频数据
                    audio_chunk = self.handle_server_response(response)
                    if audio_chunk:
                        yield audio_chunk
                        
                    # 检查是否结束
                    if response.get('event') == 359:  # TTSEnded
                        break
                        
                    # 如果没有音频数据且TTS结束，发送静音保持连接
                    if not audio_chunk and self.is_processing:
                        await self.send_silence()
                        
                except asyncio.TimeoutError:
                    logger.warning("等待响应超时，发送静音数据保持连接")
                    await self.send_silence()
                    continue
                except Exception as e:
                    logger.error(f"处理响应时出错: {e}")
                    break
            
        finally:
            self.is_processing = False
            logger.info(f"音频处理完成，收到 {len(self.audio_chunks)} 个音频块")
    
    async def send_silence(self):
        """发送静音数据保持连接 - 参考demo实现"""
        silence_data = b'\x00' * 320
        await self.client.task_request(silence_data)
    
    async def cleanup(self):
        """清理资源"""
        if self.client:
            try:
                await self.client.finish_session()
                # 等待会话结束确认
                max_wait = 50  # 最多等待5秒
                wait_count = 0
                while not self.is_session_finished and wait_count < max_wait:
                    await asyncio.sleep(0.1)
                    wait_count += 1
                    
                await self.client.finish_connection()
                await self.client.close()
                logger.info(f"已清理豆包连接资源, logid: {self.client.logid}")
            except Exception as e:
                logger.error(f"清理资源时出错: {e}")


@app.on_event("startup")
def startup_event():
    """应用启动事件"""
    logger.info("🚀 FastAPI语音处理服务启动中...")
    logger.info(f"📝 豆包App ID: {DOUBAO_CONFIG['headers']['X-Api-App-ID']}")
    logger.info("✅ 服务已启动，等待语音处理请求...")


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "豆包语音处理服务",
        "version": "1.0.0",
        "endpoints": {
            "process_voice": "/api/v1/process-voice",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "service": "doubao-voice-service"}


@app.post("/api/v1/process-voice")
async def process_voice(audio: UploadFile = File(...)):
    """
    处理语音文件
    接收客户端上传的音频文件，发送给豆包API处理，返回处理后的音频流
    """
    # 验证文件类型
    if not audio.content_type or not audio.content_type.startswith(('audio/', 'application/octet-stream')):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {audio.content_type}。请上传音频文件。"
        )
    
    try:
        # 读取上传的音频数据
        audio_data = await audio.read()
        logger.info(f"接收到音频文件: {audio.filename}, 大小: {len(audio_data)} bytes")
        
        # 创建语音处理器
        processor = VoiceProcessor()
        
        async def audio_stream():
            """音频流生成器"""
            try:
                async for chunk in processor.process_audio_file(audio_data):
                    yield chunk
            except Exception as e:
                logger.error(f"处理音频时出错: {e}")
                raise HTTPException(status_code=500, detail=f"处理音频时出错: {str(e)}")
            finally:
                await processor.cleanup()
        
        # 返回音频流响应
        return StreamingResponse(
            audio_stream(),
            media_type="audio/pcm",
            headers={
                "Content-Disposition": f"attachment; filename=processed_{audio.filename}",
                "X-Audio-Format": "pcm_s16le",
                "X-Sample-Rate": "24000",
                "X-Channels": "1"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理语音请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@app.post("/api/v1/process-voice-json")
async def process_voice_with_json_response(audio: UploadFile = File(...)):
    """
    处理语音文件并返回JSON格式结果
    包含ASR识别文本和处理后的音频数据（base64编码）
    """
    import base64
    
    if not audio.content_type or not audio.content_type.startswith(('audio/', 'application/octet-stream')):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {audio.content_type}。请上传音频文件。"
        )
    
    try:
        audio_data = await audio.read()
        logger.info(f"接收到音频文件: {audio.filename}, 大小: {len(audio_data)} bytes")
        
        processor = VoiceProcessor()
        
        # 收集所有音频块和其他信息
        audio_chunks = []
        asr_text = ""
        chat_text = ""
        
        try:
            if not await processor.connect_to_doubao():
                raise HTTPException(status_code=500, detail="无法连接到豆包API")
            
            await processor.client.task_request(audio_data)
            
            while processor.is_processing or not audio_chunks:
                processor.is_processing = True
                try:
                    response = await asyncio.wait_for(
                        processor.client.receive_server_response(),
                        timeout=30.0
                    )
                    
                    if not response:
                        continue
                    
                    event_id = response.get('event_id')
                    
                    if event_id == 352:  # TTSResponse
                        audio_chunk = response.get('payload')
                        if audio_chunk:
                            audio_chunks.append(audio_chunk)
                    
                    elif event_id == 359:  # TTSEnded
                        processor.is_processing = False
                        break
                    
                    elif event_id == 451:  # ASRResponse
                        asr_result = response.get('payload_json', {})
                        if 'results' in asr_result and asr_result['results']:
                            asr_text = asr_result['results'][0].get('text', '')
                    
                    elif event_id == 550:  # ChatResponse
                        chat_result = response.get('payload_json', {})
                        chat_text += chat_result.get('content', '')
                    
                    elif event_id in [153, 51]:  # 错误事件
                        error_msg = response.get('payload_json', {}).get('error', 'Unknown error')
                        raise Exception(f"豆包API错误: {error_msg}")
                        
                except asyncio.TimeoutError:
                    processor.is_processing = False
                    break
            
            # 合并音频数据并编码
            combined_audio = b''.join(audio_chunks)
            audio_base64 = base64.b64encode(combined_audio).decode('utf-8') if combined_audio else ""
            
            return {
                "success": True,
                "data": {
                    "asr_text": asr_text,
                    "chat_text": chat_text,
                    "audio_data": audio_base64,
                    "audio_format": "pcm_s16le",
                    "sample_rate": 24000,
                    "channels": 1,
                    "audio_length": len(combined_audio)
                }
            }
            
        finally:
            await processor.cleanup()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理语音请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_voice_service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )