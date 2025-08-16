import asyncio
import socket
import threading
from aiohttp import web


class LocalServer:
    """A tiny aiohttp server for deterministic tests.

    Routes:
        - /file_tiny         -> ~256 KB, full HEAD metadata, supports Range
        - /file_small        -> ~1.5 MB, full HEAD metadata, supports Range
        - /file_large        -> ~10 MB, full HEAD metadata, supports Range
        - /nohead_small      -> 1 MB, HEAD missing metadata; GET fills with Range
    """

    def __init__(self):
        self.data_tiny = b"TINYDATA" * 32768  # 8 * 32768 = 262,144 bytes (~256 KB)
        self.data_small = b"0123456789ABCDEF" * 1024 * 96  # ~1.5 MB
        self.data_large = b"abcdefghijklmnopqrstuvwxyz" * 1024 * 400  # ~10 MB
        self.data_nohead = b"N" * (1024 * 1024)  # 1 MB

        self._loop = None
        self._thread = None
        self._runner = None
        self._site = None
        self._app = None
        self.host = "127.0.0.1"
        self.port = None

    # --------------------------- Route Handlers ----------------------------
    async def _head_with_meta(
        self, request: web.Request, total_len: int, filename: str
    ):
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(total_len),
            "ETag": "test-etag",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        return web.Response(status=200, headers=headers)

    async def _get_with_range(self, request: web.Request, data: bytes, filename: str):
        total_len = len(data)
        rng = request.headers.get("Range") or request.headers.get("range")
        headers = {
            "Accept-Ranges": "bytes",
            "ETag": "test-etag",
            "Content-Disposition": f'attachment; filename="{filename}"',
        }
        if rng:
            try:
                units, _, rng_spec = rng.partition("=")
                if units.strip().lower() != "bytes":
                    raise ValueError
                start_s, _, end_s = rng_spec.partition("-")
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total_len - 1
                if start < 0 or end >= total_len or start > end:
                    return web.Response(status=416)
                body = data[start : end + 1]
                headers.update(
                    {
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {start}-{end}/{total_len}",
                    }
                )
                return web.Response(status=206, body=body, headers=headers)
            except Exception:
                return web.Response(status=416)
        else:
            headers.update({"Content-Length": str(total_len)})
            return web.Response(status=200, body=data, headers=headers)

    async def head_file_tiny(self, request: web.Request):
        return await self._head_with_meta(request, len(self.data_tiny), "file_tiny.bin")

    async def get_file_tiny(self, request: web.Request):
        return await self._get_with_range(request, self.data_tiny, "file_tiny.bin")

    async def head_file_small(self, request: web.Request):
        return await self._head_with_meta(
            request, len(self.data_small), "file_small.bin"
        )

    async def get_file_small(self, request: web.Request):
        return await self._get_with_range(request, self.data_small, "file_small.bin")

    async def head_file_large(self, request: web.Request):
        return await self._head_with_meta(
            request, len(self.data_large), "file_large.bin"
        )

    async def get_file_large(self, request: web.Request):
        return await self._get_with_range(request, self.data_large, "file_large.bin")

    async def head_nohead_small(self, request: web.Request):
        return web.Response(status=200)  # Intentionally no metadata

    async def get_nohead_small(self, request: web.Request):
        return await self._get_with_range(request, self.data_nohead, "nohead_small.bin")

    # --------------------------- Server Lifecycle --------------------------
    def _pick_free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            return s.getsockname()[1]

    async def _start_async(self):
        self._app = web.Application()
        self._app.router.add_route("HEAD", "/file_tiny", self.head_file_tiny)
        self._app.router.add_route("GET", "/file_tiny", self.get_file_tiny)
        self._app.router.add_route("HEAD", "/file_small", self.head_file_small)
        self._app.router.add_route("GET", "/file_small", self.get_file_small)
        self._app.router.add_route("HEAD", "/file_large", self.head_file_large)
        self._app.router.add_route("GET", "/file_large", self.get_file_large)
        self._app.router.add_route("HEAD", "/nohead_small", self.head_nohead_small)
        self._app.router.add_route("GET", "/nohead_small", self.get_nohead_small)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self.port = self.port or self._pick_free_port()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    def start(self):
        if self._thread:
            return

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._start_async())
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        while self.port is None:
            pass

    async def _stop_async(self):
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    def stop(self):
        if not self._thread:
            return
        if self._loop and self._loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._stop_async(), self._loop)
            fut.result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._thread = None
        self._loop = None

    @property
    def base_url(self) -> str:
        if not self.port:
            raise RuntimeError("Server not started")
        return f"http://{self.host}:{self.port}"
