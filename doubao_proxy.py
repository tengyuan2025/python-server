#!/usr/bin/env python3
"""
豆包实时语音API WebSocket代理服务器
用于处理浏览器无法设置自定义headers的问题
"""

import asyncio
import websockets
import json
import uuid
import struct
from aiohttp import web
import logging
from typing import Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# API配置
CONFIG = {
    'APP_ID': '7059594059',
    'ACCESS_KEY': 'tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt',
    'RESOURCE_ID': 'volc.speech.dialog',
    'APP_KEY': 'PlgvMymc7f3tQnJ6',
    'DOUBAO_WS_URL': 'wss://openspeech.bytedance.com/api/v3/realtime/dialogue',
    'LOCAL_WS_PORT': 8765,
    'LOCAL_HTTP_PORT': 8766
}

# 存储客户端连接
client_connections = {}

def parse_binary_frame(data: bytes) -> dict:
    """解析二进制帧（用于调试）"""
    try:
        if len(data) < 4:
            return {'error': 'Frame too short'}
        
        offset = 0
        byte1 = data[offset + 1]
        message_type = (byte1 >> 4) & 0x0F
        flags = byte1 & 0x0F
        
        offset = 4
        event_id = None
        
        # 错误帧
        if message_type == 0x0F:
            offset += 4
        
        # Event ID
        if flags & 0x04:
            event_id = struct.unpack('>I', data[offset:offset+4])[0]
            offset += 4
        
        return {
            'message_type': hex(message_type),
            'flags': hex(flags),
            'event_id': event_id
        }
    except Exception as e:
        return {'error': str(e)}

async def handle_client_connection(client_ws):
    """处理客户端WebSocket连接"""
    client_id = str(uuid.uuid4())
    logger.info(f"📱 客户端连接建立: {client_id}")
    
    doubao_ws = None
    
    try:
        # 连接到豆包服务器
        connect_id = str(uuid.uuid4())
        logger.info(f"🔑 Connect ID: {connect_id}")
        
        headers = {
            'X-Api-App-ID': CONFIG['APP_ID'],
            'X-Api-Access-Key': CONFIG['ACCESS_KEY'],
            'X-Api-Resource-Id': CONFIG['RESOURCE_ID'],
            'X-Api-App-Key': CONFIG['APP_KEY'],
            'X-Api-Connect-Id': connect_id
        }
        
        # 连接豆包WebSocket
        doubao_ws = await websockets.connect(
            CONFIG['DOUBAO_WS_URL'],
            additional_headers=headers
        )
        
        logger.info("✅ 已连接到豆包服务器")
        
        # 通知客户端连接成功
        await client_ws.send(json.dumps({
            'type': 'proxy_connected',
            'message': '代理服务器已连接到豆包API',
            'connect_id': connect_id
        }))
        
        # 存储连接信息
        client_connections[client_id] = {
            'client_ws': client_ws,
            'doubao_ws': doubao_ws,
            'connect_id': connect_id
        }
        
        # 创建双向转发任务
        client_to_doubao = asyncio.create_task(
            forward_messages(client_ws, doubao_ws, "客户端->豆包")
        )
        doubao_to_client = asyncio.create_task(
            forward_messages(doubao_ws, client_ws, "豆包->客户端")
        )
        
        # 等待任一方向结束
        done, pending = await asyncio.wait(
            [client_to_doubao, doubao_to_client],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # 取消未完成的任务
        for task in pending:
            task.cancel()
            
    except websockets.exceptions.WebSocketException as e:
        logger.error(f"❌ WebSocket错误: {e}")
        if client_ws and not client_ws.closed:
            await client_ws.send(json.dumps({
                'type': 'proxy_error',
                'error': str(e)
            }))
    except Exception as e:
        logger.error(f"❌ 未知错误: {e}")
    finally:
        # 清理连接
        if client_id in client_connections:
            del client_connections[client_id]
        
        if doubao_ws and doubao_ws.close_code is None:
            await doubao_ws.close()
        
        if client_ws and client_ws.close_code is None:
            await client_ws.close()
        
        logger.info(f"🔌 连接关闭: {client_id}")

async def forward_messages(from_ws, to_ws, direction):
    """转发消息"""
    try:
        async for message in from_ws:
            if to_ws.close_code is not None:
                break
                
            # 解析并记录消息（调试用）
            if isinstance(message, bytes):
                frame_info = parse_binary_frame(message)
                logger.debug(f"📦 {direction}: {frame_info}")
            else:
                logger.debug(f"📝 {direction}: 文本消息")
            
            # 转发消息
            await to_ws.send(message)
            
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"🔌 {direction} 连接关闭")
    except Exception as e:
        logger.error(f"❌ {direction} 转发错误: {e}")

async def handle_http_request(request):
    """处理HTTP请求"""
    if request.path == '/':
        html_content = f"""
        <!DOCTYPE html>
        <html lang="zh">
        <head>
            <meta charset="UTF-8">
            <title>豆包语音代理服务器</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 40px; }}
                .container {{ max-width: 800px; margin: 0 auto; }}
                .info {{ background: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .warning {{ background: #fff3e0; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .error {{ background: #ffebee; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; font-size: 1.2em; }}
                .status {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: bold; }}
                .status.running {{ background: #4caf50; color: white; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🚀 豆包语音代理服务器</h1>
                
                <div class="info">
                    <h2>服务状态</h2>
                    <p><span class="status running">运行中</span></p>
                    <p>WebSocket端口: <code>{CONFIG['LOCAL_WS_PORT']}</code></p>
                    <p>HTTP端口: <code>{CONFIG['LOCAL_HTTP_PORT']}</code></p>
                    <p>活动连接数: <code>{len(client_connections)}</code></p>
                </div>
                
                <div class="warning">
                    <h2>使用说明</h2>
                    <ol>
                        <li>确保 <code>realtime_test.html</code> 已更新为连接本地代理</li>
                        <li>在浏览器中打开 HTML 文件</li>
                        <li>点击"连接服务"按钮</li>
                        <li>开始语音对话</li>
                    </ol>
                </div>
                
                <div class="info">
                    <h2>配置信息</h2>
                    <p>App ID: <code>{CONFIG['APP_ID']}</code></p>
                    <p>豆包API: <code>{CONFIG['DOUBAO_WS_URL']}</code></p>
                    <p>本地代理: <code>ws://localhost:{CONFIG['LOCAL_WS_PORT']}</code></p>
                </div>
                
                <div class="warning">
                    <h2>测试工具</h2>
                    <p><a href="/test">打开测试页面</a></p>
                </div>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')
    
    elif request.path == '/status':
        status = {
            'status': 'running',
            'connections': len(client_connections),
            'config': {
                'app_id': CONFIG['APP_ID'],
                'ws_port': CONFIG['LOCAL_WS_PORT'],
                'http_port': CONFIG['LOCAL_HTTP_PORT']
            }
        }
        return web.json_response(status)
    
    elif request.path == '/test':
        # 返回realtime_test.html的内容（如果需要）
        return web.Response(text="请直接打开 realtime_test.html 文件进行测试", content_type='text/plain')
    
    return web.Response(text='Not Found', status=404)

async def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🚀 豆包语音代理服务器启动中...")
    logger.info(f"📝 App ID: {CONFIG['APP_ID']}")
    logger.info(f"🔑 Access Key: {CONFIG['ACCESS_KEY'][:10]}...")
    logger.info("=" * 60)
    
    # 启动WebSocket服务器
    ws_server = await websockets.serve(
        handle_client_connection,
        'localhost',
        CONFIG['LOCAL_WS_PORT']
    )
    
    # 启动HTTP服务器
    app = web.Application()
    app.router.add_get('/', handle_http_request)
    app.router.add_get('/status', handle_http_request)
    app.router.add_get('/test', handle_http_request)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', CONFIG['LOCAL_HTTP_PORT'])
    await site.start()
    
    logger.info(f"📡 WebSocket服务: ws://localhost:{CONFIG['LOCAL_WS_PORT']}")
    logger.info(f"🌐 HTTP服务: http://localhost:{CONFIG['LOCAL_HTTP_PORT']}")
    logger.info("\n等待客户端连接...\n")
    
    try:
        # 保持服务运行
        await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("\n👋 正在关闭服务器...")
    finally:
        ws_server.close()
        await ws_server.wait_closed()
        await runner.cleanup()
        logger.info("✅ 服务器已关闭")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 服务器已停止")