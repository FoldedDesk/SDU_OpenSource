"""按统一 YAML 配置启动本地演示。""" # 模块说明。
import uvicorn  # 提供 ASGI 服务。

from app.core import load_config  # 端口和监听地址不散落在代码中。

if __name__ == "__main__":  # 仅直接运行模块时启动服务。
    config = load_config()  # 读取本地配置。
    uvicorn.run("app.main:app", host=config["app"]["host"], port=config["app"]["port"])  # 本机可通过配置切换端口。
