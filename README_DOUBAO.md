# 豆包实时语音对话系统

## 快速开始

### 1. 安装依赖
```bash
pip3 install websockets aiohttp
```

### 2. 启动代理服务器
```bash
# 方式1: 使用启动脚本
./start_doubao.sh

# 方式2: 直接运行Python
python3 doubao_proxy.py
```

### 3. 打开测试页面
在浏览器中打开 `realtime_test.html` 文件

### 4. 开始对话
1. 点击"连接服务"按钮
2. 点击"开始对话"按钮
3. 开始说话，系统会自动识别并回复

## 系统架构

```
浏览器 (realtime_test.html)
    ↓ WebSocket
代理服务器 (doubao_proxy.py) 
    ↓ WebSocket + Headers认证
豆包API (openspeech.bytedance.com)
```

## 功能特性

### 实时语音识别 (ASR)
- 实时返回识别结果
- 支持中断词检测
- 显示部分和最终结果

### 语音合成 (TTS)  
- 支持4种音色选择
- 支持Opus和PCM格式
- 流式音频播放

### 对话管理
- 支持多轮对话
- 对话历史记录
- Token使用统计

## 配置说明

代理服务器已配置以下认证信息：
- App ID: 7059594059
- Access Key: tRDp6c2pMhqtMXWYCINDSCDQPyfaWZbt

## 端口说明

- WebSocket代理: `ws://localhost:8765`
- HTTP状态页面: `http://localhost:8766`

## 调试信息

查看服务器日志了解：
- 连接状态
- 事件ID
- 消息类型
- 错误信息

## 注意事项

1. 确保麦克风权限已开启
2. 使用Chrome或Firefox浏览器
3. 保持网络连接稳定
4. 代理服务器必须在使用前启动

## 故障排除

### 无法连接
- 检查代理服务器是否运行
- 确认端口8765未被占用

### 无法录音
- 检查浏览器麦克风权限
- 确认使用HTTPS或localhost

### 无声音输出
- 检查音频格式设置
- 确认浏览器音频权限