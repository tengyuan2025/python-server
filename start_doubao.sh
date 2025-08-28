#!/bin/bash

echo "🚀 启动豆包实时语音服务"
echo "================================"
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: Python3 未安装"
    exit 1
fi

# 创建虚拟环境（如果不存在）
VENV_DIR="venv_doubao"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建Python虚拟环境..."
    python3 -m venv $VENV_DIR
fi

# 激活虚拟环境
echo "🔧 激活虚拟环境..."
source $VENV_DIR/bin/activate

# 安装依赖包
echo "📦 安装依赖包..."
pip install websockets aiohttp > /dev/null 2>&1

# 启动代理服务器
echo "🔧 启动代理服务器..."
echo "📡 WebSocket: ws://localhost:8765"
echo "🌐 HTTP状态: http://localhost:8766"
echo ""
echo "✅ 代理服务器已配置认证信息:"
echo "   App ID: 7059594059"
echo "   Access Key: tRDp6c2pMh...（已隐藏）"
echo ""
echo "📝 使用说明:"
echo "1. 在浏览器中打开 realtime_test.html"
echo "2. 点击 '连接服务' 按钮"
echo "3. 点击 '开始对话' 进行语音交互"
echo ""
echo "按 Ctrl+C 停止服务器"
echo "================================"
echo ""

# 启动Python代理服务器
python3 doubao_proxy.py