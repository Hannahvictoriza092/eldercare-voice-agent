"""可视化演示包。

- sim_qwen.py  模拟 Qwen（规则版意图识别，输出格式对齐真 Qwen 的 tool_call）
- runtime.py   把三个 skill 装进隔离环境，跑一句话返回可渲染的轨迹
- app.py       Gradio 网页界面（唯一依赖 gradio 的文件）
- selftest.py  不开网页的命令行自检
"""
