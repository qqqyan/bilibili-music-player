"""路由层(Controller 层):按业务域拆分,只做参数解析与响应组装。

业务逻辑在 Service 层(bilibili_client / download_manager / stream_proxy 等),
持久化在 Repository 层(*_store)。
"""
