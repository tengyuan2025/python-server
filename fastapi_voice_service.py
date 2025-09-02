#!/usr/bin/env python3
"""
基于FastAPI的语音处理服务
接收客户端语音文件，转发给豆包实时语音API，并返回处理结果
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, WebSocket
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
            logger.info(f"正在连接豆包API, session_id: {self.session_id}")
            self.client = RealtimeDialogClient(
                config=DOUBAO_CONFIG,
                session_id=self.session_id,
                output_audio_format="pcm_s16le"
            )
            logger.info("建立WebSocket连接并发送StartSession请求...")
            await self.client.connect()
            logger.info(f"✅ 成功连接到豆包API并完成会话初始化, session_id: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 连接豆包API失败: {e}")
            self.client = None  # 确保清空client
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
                logger.info("✅ ASR结束，用户说话完成，等待对话生成...")
                # ASR结束后，豆包API会开始生成对话响应
                
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
        logger.info(f"🎵 开始处理音频文件，数据长度: {len(audio_data)} bytes")
        
        # 暂时移除音频块大小检查，因为需要在API层面进行多块音频的统一检查
        logger.info(f"📊 接收音频数据：大小 {len(audio_data)} 字节")
        
        # 检查连接状态，如果没有连接才建立
        if not self.client:
            logger.info("客户端未连接，尝试建立连接...")
            if not await self.connect_to_doubao():
                error_msg = "无法连接到豆包API，请检查网络和配置"
                logger.error(error_msg)
                raise Exception(error_msg)
        
        logger.info("🔄 进入process_audio_file主处理逻辑")
        
        try:
            self.is_processing = True
            self.audio_chunks = []
            
            logger.info(f"📤 开始发送音频数据到豆包API...")
            
            # 按chunk分块发送音频数据（参考demo实现）
            chunk_size = 3200  # 与demo中的配置一致
            chunks_sent = 0
            total_sent = 0
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                if chunk:
                    await self.client.task_request(chunk)
                    chunks_sent += 1
                    total_sent += len(chunk)
                    logger.info(f"发送音频块 #{chunks_sent}: {len(chunk)} bytes (累计: {total_sent}/{len(audio_data)} bytes)")
            
            logger.info("📤 音频数据发送完成")
            
            # 发送长静音触发VAD结束检测
            logger.info("🔇 发送长静音数据触发VAD结束检测...")
            await self.send_long_silence()
            
            # 发送空音频包标记输入结束
            logger.info("🏁 发送空音频包标记音频输入结束...")
            await self.send_audio_end_signal()
            
            logger.info("✅ 音频输入完成，等待豆包API处理并生成响应...")
            
            # 启动接收循环
            response_count = 0
            received_any_response = False
            silence_count = 0
            
            # 确保至少尝试接收一次响应
            max_iterations = 100  # 最多尝试100次，防止无限循环
            iteration = 0
            
            while (self.is_processing and not self.is_session_finished) and iteration < max_iterations:
                iteration += 1
                logger.info(f"[第{iteration}次] 循环条件检查 - is_processing: {self.is_processing}, is_session_finished: {self.is_session_finished}")
                try:
                    logger.info(f"[第{iteration}次] 等待豆包API响应... (已接收 {response_count} 个有效响应)")
                    logger.info(f"[第{iteration}次] 调用 receive_server_response()...")
                    response = await asyncio.wait_for(
                        self.client.receive_server_response(),
                        timeout=5.0  # 减少超时时间
                    )
                    logger.info(f"[第{iteration}次] receive_server_response() 返回: {response}")
                    
                    response_count += 1
                    received_any_response = True
                    logger.info(f"📥 接收到响应 #{response_count}: {type(response)} - {response}")
                    
                    # 检查响应是否为空
                    if not response:
                        logger.warning(f"接收到空响应，继续等待...")
                        continue
                    
                    # 处理响应并获取音频数据
                    audio_chunk = self.handle_server_response(response)
                    if audio_chunk:
                        logger.info(f"🔊 生成音频块: {len(audio_chunk)} bytes")
                        yield audio_chunk
                        
                    # 检查是否结束
                    if response.get('event') == 359:  # TTSEnded
                        logger.info("收到TTS结束信号，退出处理循环")
                        break
                        
                    # 继续发送静音保持连接
                    if self.is_processing:
                        silence_count += 1
                        logger.debug(f"发送静音数据保持连接 #{silence_count}")
                        await self.send_silence()
                        
                except asyncio.TimeoutError:
                    logger.warning("⏰ 等待响应超时，发送静音数据保持连接")
                    if not received_any_response:
                        # 发送静音数据尝试激活处理
                        silence_count += 1
                        logger.info(f"发送静音数据尝试激活处理 #{silence_count}")
                        await self.send_silence()
                        
                        # 如果发送了很多静音数据还没收到响应，则退出
                        if silence_count > 1:
                            logger.error("❌ 发送了大量静音数据仍未收到响应，连接可能有问题")
                            break
                    else:
                        await self.send_silence()
                    continue
                except Exception as e:
                    logger.error(f"❌ 处理响应时出错: {e}")
                    import traceback
                    logger.error(f"异常详情: {traceback.format_exc()}")
                    
                    # 检查是否是连接问题
                    if "ConnectionClosed" in str(e) or "Connection closed" in str(e):
                        logger.error("🔌 WebSocket连接已关闭，可能是客户端断开连接")
                    elif "Failed to receive message" in str(e):
                        logger.error("📡 接收消息失败，WebSocket可能异常")
                    
                    break
            
        finally:
            self.is_processing = False
            logger.info(f"🏁 音频处理结束 - 总迭代次数: {iteration}, 收到响应: {response_count}, 音频块: {len(self.audio_chunks)}")
            if iteration >= max_iterations:
                logger.warning("⚠️ 达到最大迭代次数限制，强制退出")
    
    async def send_silence(self):
        """发送静音数据保持连接 - 参考demo实现"""
        silence_data = b'\x00' * 320
        await self.client.task_request(silence_data)
    
    async def send_audio_end_signal(self):
        """发送空音频包，标记音频输入结束"""
        empty_audio = b''  # 空字节，长度为0
        await self.client.task_request(empty_audio)
        logger.info("📭 发送空音频包，标记音频输入结束")
    
    async def send_long_silence(self):
        """发送长静音数据触发VAD结束检测"""
        # 发送1.5秒的静音（16000Hz * 2bytes * 1.5s = 48000 bytes）
        long_silence = b'\x00' * 48000
        
        # 分块发送，避免数据包过大
        chunk_size = 3200
        chunks_sent = 0
        for i in range(0, len(long_silence), chunk_size):
            chunk = long_silence[i:i + chunk_size]
            await self.client.task_request(chunk)
            chunks_sent += 1
            await asyncio.sleep(0.01)  # 模拟真实音频流的时间间隔
        
        logger.info(f"📢 发送了1.5秒静音数据（{chunks_sent}个块，共{len(long_silence)}字节）")
    
    async def cleanup(self):
        """清理资源"""
        if self.client:
            try:
                logger.info("开始清理豆包API连接资源...")
                await self.client.finish_session()
                # 等待会话结束确认
                max_wait = 50  # 最多等待5秒
                wait_count = 0
                while not self.is_session_finished and wait_count < max_wait:
                    await asyncio.sleep(0.1)
                    wait_count += 1
                    
                await self.client.finish_connection()
                await self.client.close()
                logger.info(f"✅ 已清理豆包连接资源, logid: {getattr(self.client, 'logid', 'unknown')}")
            except Exception as e:
                logger.error(f"❌ 清理资源时出错: {e}")
        else:
            logger.warning("⚠️  没有需要清理的豆包API连接")


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


@app.post("/api/v1/process-voice-debug")
async def process_voice_debug(request: Request):
    """
    调试接口 - 显示ESP32发送的原始请求信息
    """
    
    # 获取请求信息
    headers = dict(request.headers)
    content_type = headers.get('content-type', 'Not specified')
    
    # 读取原始请求体
    body = await request.body()
    
    logger.info(f"=== ESP32请求调试信息 ===")
    logger.info(f"Content-Type: {content_type}")
    logger.info(f"Headers: {headers}")
    logger.info(f"Body length: {len(body)} bytes")
    logger.info(f"Body preview (first 100 bytes): {body[:100]}")
    
    return {
        "message": "Debug info logged",
        "content_type": content_type,
        "body_length": len(body),
        "headers": headers
    }


# 用于存储音频会话数据
audio_sessions = {}

@app.post("/api/v1/process-voice-session-start")
async def start_voice_session():
    """开始一个新的音频会话，返回会话ID"""
    session_id = str(uuid.uuid4())
    audio_sessions[session_id] = {
        "audio_data": b'',
        "created_at": asyncio.get_event_loop().time(),
        "chunk_count": 0
    }
    logger.info(f"🎬 创建新的音频会话: {session_id}")
    return {"session_id": session_id}

@app.post("/api/v1/process-voice-session-append/{session_id}")
async def append_voice_data(session_id: str, request: Request):
    """向会话追加音频数据"""
    if session_id not in audio_sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    audio_chunk = await request.body()
    audio_sessions[session_id]["audio_data"] += audio_chunk
    audio_sessions[session_id]["chunk_count"] += 1
    
    logger.info(f"📝 会话 {session_id} 追加音频块 #{audio_sessions[session_id]['chunk_count']}: {len(audio_chunk)} bytes, 总计: {len(audio_sessions[session_id]['audio_data'])} bytes")
    return {"status": "ok", "total_bytes": len(audio_sessions[session_id]["audio_data"])}

@app.post("/api/v1/process-voice-session-process/{session_id}")
async def process_voice_session(session_id: str):
    """处理会话中累积的音频数据"""
    if session_id not in audio_sessions:
        raise HTTPException(status_code=404, detail="会话不存在")
    
    session_data = audio_sessions.pop(session_id)
    audio_data = session_data["audio_data"]
    
    logger.info(f"🎯 处理会话 {session_id} 的音频数据: {len(audio_data)} bytes ({session_data['chunk_count']} 个块)")
    
    if not audio_data:
        raise HTTPException(status_code=400, detail="没有音频数据")
    
    # 使用原有的处理逻辑
    processor = VoiceProcessor()
    
    if not await processor.connect_to_doubao():
        raise HTTPException(status_code=503, detail="无法连接到豆包API服务")
    
    async def audio_stream():
        try:
            logger.info("🎬 开始音频流生成器（会话模式）")
            chunk_count = 0
            async for chunk in processor.process_audio_file(audio_data):
                chunk_count += 1
                logger.info(f"🎵 生成音频流块 #{chunk_count}: {len(chunk)} bytes")
                yield chunk
            logger.info(f"✅ 音频流生成完成，总共生成 {chunk_count} 个音频块")
        except GeneratorExit:
            logger.warning("⚠️ 客户端提前断开连接")
            raise
        except Exception as e:
            logger.error(f"❌ 处理音频时出错: {e}")
            raise
        finally:
            logger.info("🔚 音频流生成器结束")
            await processor.cleanup()
    
    return StreamingResponse(
        audio_stream(),
        media_type="audio/pcm",
        headers={
            "Content-Disposition": f"attachment; filename=processed_audio.pcm",
            "X-Audio-Format": "pcm_s16le",
            "X-Sample-Rate": "24000",
            "X-Channels": "1"
        }
    )

@app.post("/api/v1/process-voice-raw")
async def process_voice_raw(request: Request):
    """
    处理原始音频数据（适用于ESP32直接发送PCM数据）
    ESP32可以直接POST原始音频数据，无需multipart/form-data封装
    """
    try:
        # 直接读取请求体作为音频数据
        audio_data = await request.body()
        
        if not audio_data:
            raise HTTPException(status_code=400, detail="未接收到音频数据")
            
        logger.info(f"接收到原始音频数据: {len(audio_data)} bytes")
        
        # 检查音频块大小 - 拦截小于5000字节的音频块
        min_block_size = 5000
        if len(audio_data) < min_block_size:
            logger.warning(f"❌ 拦截小音频块：{len(audio_data)} 字节 < {min_block_size} 字节")
            raise HTTPException(
                status_code=400, 
                detail=f"音频块太小，仅{len(audio_data)}字节，需要至少{min_block_size}字节"
            )
        
        # 检查音频长度是否满足最小要求
        MIN_AUDIO_SIZE = 8000  # 最小8000字节 (0.25秒)
        if len(audio_data) < MIN_AUDIO_SIZE:
            logger.warning(f"❌ 音频数据太短: {len(audio_data)} bytes，需要至少 {MIN_AUDIO_SIZE} bytes (0.25秒)")
            raise HTTPException(
                status_code=400, 
                detail=f"音频数据太短，需要至少{MIN_AUDIO_SIZE}字节(0.25秒)的音频数据，当前仅有{len(audio_data)}字节"
            )
        
        # 打印音频数据的前几个字节，判断是否是有效音频
        if len(audio_data) > 10:
            # 检查是否全是静音（0x00）
            is_silence = all(b == 0 for b in audio_data[:100])
            logger.info(f"音频数据检查 - 前100字节是否静音: {is_silence}")
            
            # 计算音频时长（假设16kHz, 16bit单声道）
            duration = len(audio_data) / (16000 * 2)  # 16kHz * 2bytes
            logger.info(f"音频时长估算: {duration:.2f}秒")
        
        # 创建语音处理器
        processor = VoiceProcessor()
        
        # 预先测试连接
        if not await processor.connect_to_doubao():
            raise HTTPException(status_code=503, detail="无法连接到豆包API服务")
        
        async def audio_stream():
            """音频流生成器"""
            try:
                logger.info("🎬 开始音频流生成器")
                chunk_count = 0
                async for chunk in processor.process_audio_file(audio_data):
                    chunk_count += 1
                    logger.info(f"🎵 生成音频流块 #{chunk_count}: {len(chunk)} bytes")
                    yield chunk
                logger.info(f"✅ 音频流生成完成，总共生成 {chunk_count} 个音频块")
            except GeneratorExit:
                logger.warning("⚠️ 客户端提前断开连接，停止音频流生成")
                raise
            except Exception as e:
                logger.error(f"❌ 处理音频时出错: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise HTTPException(status_code=500, detail=f"处理音频时出错: {str(e)}")
            finally:
                logger.info("🔚 音频流生成器结束，开始清理资源")
                await processor.cleanup()
        
        # 返回音频流响应
        return StreamingResponse(
            audio_stream(),
            media_type="audio/pcm",
            headers={
                "Content-Disposition": f"attachment; filename=processed_audio.pcm",
                "X-Audio-Format": "pcm_s16le",
                "X-Sample-Rate": "24000",
                "X-Channels": "1"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理原始音频请求时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@app.post("/api/v1/process-voice")
async def process_voice(audio: UploadFile = File(...)):
    """
    处理语音文件（标准multipart/form-data格式）
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


@app.websocket("/ws/voice")
async def websocket_voice(websocket: WebSocket):
    """WebSocket语音处理端点 - 适用于ESP32实时通信"""
    await websocket.accept()
    logger.info(f"🔌 WebSocket连接建立: {websocket.client}")
    
    try:
        while True:
            # 接收音频数据
            audio_data = await websocket.receive_bytes()
            logger.info(f"📡 WebSocket接收音频数据: {len(audio_data)} bytes")
            
            # 处理音频
            processor = VoiceProcessor()
            
            try:
                if not await processor.connect_to_doubao():
                    await websocket.send_text('{"error": "无法连接到豆包API"}')
                    continue
                
                # 处理音频并发送响应
                async for chunk in processor.process_audio_file(audio_data):
                    await websocket.send_bytes(chunk)
                    
                await websocket.send_text('{"status": "completed"}')
                
            except Exception as e:
                logger.error(f"WebSocket处理音频出错: {e}")
                await websocket.send_text(f'{{"error": "{str(e)}"}}')
            finally:
                await processor.cleanup()
                
    except Exception as e:
        logger.error(f"WebSocket连接错误: {e}")
    finally:
        logger.info("🔌 WebSocket连接关闭")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_voice_service:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )