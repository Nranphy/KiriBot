"""本机 Gateway 的网络地址处理"""


def gateway_url_host(listen_host: str) -> str:
    """将监听地址转换为本机客户端可用于 URL 的主机部分"""
    if listen_host == '0.0.0.0':
        return '127.0.0.1'
    if listen_host == '::':
        return '[::1]'
    if ':' in listen_host and not listen_host.startswith('['):
        return f'[{listen_host}]'
    return listen_host
