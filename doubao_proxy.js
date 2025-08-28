const WebSocket = require('ws');
const http = require('http');
const url = require('url');

// 配置
const CONFIG = {
    APP_ID: '7059594059',
    ACCESS_KEY: 'tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt',
    RESOURCE_ID: 'volc.speech.dialog',
    APP_KEY: 'PlgvMymc7f3tQnJ6',
    DOUBAO_WS_URL: 'wss://openspeech.bytedance.com/api/v3/realtime/dialogue',
    LOCAL_PORT: 8765
};

// 创建HTTP服务器
const server = http.createServer();

// 创建WebSocket服务器
const wss = new WebSocket.Server({ server });

console.log(`🚀 豆包语音代理服务器启动在端口 ${CONFIG.LOCAL_PORT}`);
console.log(`📝 配置信息:`, {
    APP_ID: CONFIG.APP_ID,
    ACCESS_KEY: CONFIG.ACCESS_KEY.substring(0, 10) + '...'
});

// 处理客户端连接
wss.on('connection', (clientWs, req) => {
    console.log('📱 客户端连接建立');
    
    // 生成connect ID
    const connectId = generateUUID();
    console.log(`🔑 Connect ID: ${connectId}`);
    
    // 连接到豆包服务器
    const doubaoWs = new WebSocket(CONFIG.DOUBAO_WS_URL, {
        headers: {
            'X-Api-App-ID': CONFIG.APP_ID,
            'X-Api-Access-Key': CONFIG.ACCESS_KEY,
            'X-Api-Resource-Id': CONFIG.RESOURCE_ID,
            'X-Api-App-Key': CONFIG.APP_KEY,
            'X-Api-Connect-Id': connectId
        }
    });
    
    doubaoWs.binaryType = 'arraybuffer';
    
    // 豆包服务器连接成功
    doubaoWs.on('open', () => {
        console.log('✅ 已连接到豆包服务器');
        
        // 通知客户端连接成功
        if (clientWs.readyState === WebSocket.OPEN) {
            clientWs.send(JSON.stringify({
                type: 'proxy_connected',
                message: '代理服务器已连接到豆包API'
            }));
        }
    });
    
    // 处理豆包服务器消息
    doubaoWs.on('message', (data) => {
        // 直接转发二进制数据到客户端
        if (clientWs.readyState === WebSocket.OPEN) {
            if (data instanceof Buffer || data instanceof ArrayBuffer) {
                // 打印事件信息（调试用）
                try {
                    const frame = parseBinaryFrame(data);
                    console.log(`📩 豆包->客户端: 事件ID=${frame.eventId}, 类型=${frame.messageType.toString(16)}`);
                } catch (e) {
                    console.log(`📩 豆包->客户端: 二进制数据 ${data.byteLength} bytes`);
                }
            }
            clientWs.send(data);
        }
    });
    
    // 处理豆包服务器错误
    doubaoWs.on('error', (error) => {
        console.error('❌ 豆包服务器错误:', error.message);
        if (clientWs.readyState === WebSocket.OPEN) {
            clientWs.send(JSON.stringify({
                type: 'proxy_error',
                error: error.message
            }));
        }
    });
    
    // 豆包服务器关闭连接
    doubaoWs.on('close', (code, reason) => {
        console.log(`🔌 豆包服务器断开连接: ${code} - ${reason}`);
        if (clientWs.readyState === WebSocket.OPEN) {
            clientWs.close();
        }
    });
    
    // 处理客户端消息
    clientWs.on('message', (data) => {
        // 直接转发到豆包服务器
        if (doubaoWs.readyState === WebSocket.OPEN) {
            if (data instanceof Buffer || data instanceof ArrayBuffer) {
                // 打印事件信息（调试用）
                try {
                    const frame = parseBinaryFrame(data);
                    console.log(`📤 客户端->豆包: 事件ID=${frame.eventId}, 类型=${frame.messageType.toString(16)}`);
                } catch (e) {
                    console.log(`📤 客户端->豆包: 二进制数据 ${data.byteLength} bytes`);
                }
            }
            doubaoWs.send(data);
        }
    });
    
    // 客户端断开连接
    clientWs.on('close', () => {
        console.log('📱 客户端断开连接');
        if (doubaoWs.readyState === WebSocket.OPEN) {
            doubaoWs.close();
        }
    });
    
    // 客户端错误
    clientWs.on('error', (error) => {
        console.error('❌ 客户端错误:', error.message);
    });
});

// 解析二进制帧（用于调试日志）
function parseBinaryFrame(data) {
    const buffer = data instanceof ArrayBuffer ? data : data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
    const view = new DataView(buffer);
    let offset = 0;
    
    // Parse header
    const byte0 = view.getUint8(offset++);
    const byte1 = view.getUint8(offset++);
    const byte2 = view.getUint8(offset++);
    const byte3 = view.getUint8(offset++);
    
    const messageType = (byte1 >> 4) & 0x0F;
    const flags = byte1 & 0x0F;
    
    let eventId = null;
    
    // Error code (if error frame)
    if (messageType === 0x0F) {
        offset += 4;
    }
    
    // Event ID
    if (flags & 0x04) {
        eventId = view.getUint32(offset, false);
        offset += 4;
    }
    
    return {
        messageType,
        flags,
        eventId
    };
}

// 生成UUID
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// 创建静态文件服务器（提供HTML页面）
server.on('request', (req, res) => {
    const parsedUrl = url.parse(req.url);
    
    // 提供状态端点
    if (parsedUrl.pathname === '/status') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
            status: 'running',
            connections: wss.clients.size,
            config: {
                app_id: CONFIG.APP_ID,
                ws_port: CONFIG.LOCAL_PORT
            }
        }));
        return;
    }
    
    // 根路径返回使用说明
    if (parsedUrl.pathname === '/') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(`
            <html>
            <head>
                <title>豆包语音代理服务器</title>
                <style>
                    body { font-family: sans-serif; margin: 40px; }
                    .info { background: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0; }
                    .warning { background: #fff3e0; padding: 20px; border-radius: 8px; margin: 20px 0; }
                    code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; }
                </style>
            </head>
            <body>
                <h1>🚀 豆包语音代理服务器</h1>
                <div class="info">
                    <h2>服务状态</h2>
                    <p>✅ 代理服务器运行中...</p>
                    <p>WebSocket端口: <code>${CONFIG.LOCAL_PORT}</code></p>
                    <p>App ID: <code>${CONFIG.APP_ID}</code></p>
                </div>
                <div class="warning">
                    <h2>使用说明</h2>
                    <p>1. 打开 <code>realtime_test.html</code> 文件</p>
                    <p>2. WebSocket将自动连接到 <code>ws://localhost:${CONFIG.LOCAL_PORT}</code></p>
                    <p>3. 无需手动输入 App ID 和 Access Key（已在代理服务器配置）</p>
                    <p>4. 点击"连接服务"即可开始使用</p>
                </div>
                <div class="info">
                    <h2>API端点</h2>
                    <p>WebSocket: <code>ws://localhost:${CONFIG.LOCAL_PORT}</code></p>
                    <p>状态检查: <code>http://localhost:${CONFIG.LOCAL_PORT}/status</code></p>
                </div>
            </body>
            </html>
        `);
        return;
    }
    
    // 404
    res.writeHead(404);
    res.end('Not Found');
});

// 启动服务器
server.listen(CONFIG.LOCAL_PORT, () => {
    console.log(`\n🌐 访问 http://localhost:${CONFIG.LOCAL_PORT} 查看状态`);
    console.log(`📡 WebSocket代理地址: ws://localhost:${CONFIG.LOCAL_PORT}`);
    console.log('\n等待客户端连接...\n');
});

// 优雅退出
process.on('SIGINT', () => {
    console.log('\n👋 正在关闭服务器...');
    wss.clients.forEach(client => client.close());
    server.close(() => {
        console.log('✅ 服务器已关闭');
        process.exit(0);
    });
});