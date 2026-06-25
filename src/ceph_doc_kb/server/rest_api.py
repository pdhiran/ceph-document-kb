"""REST API for Ceph documentation knowledge base."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ceph_doc_kb.server.mcp_server import CephDocMCPServer, _load_config, _resolve_kb_path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _create_doc_server(kb_path: str | None, version: str | None) -> CephDocMCPServer:
    config = _load_config()
    resolved = _resolve_kb_path(kb_path, version)
    server = CephDocMCPServer(resolved, config)
    server._load()
    return server


def create_app(kb_path: str | None = None, version: str | None = None) -> Starlette:
    doc_server = _create_doc_server(kb_path, version)

    async def search(request: Request) -> JSONResponse:
        query = request.query_params.get("query")
        if not query:
            return _error(400, "Missing required parameter: query")
        component = request.query_params.get("component")
        try:
            limit = int(request.query_params.get("limit", 10))
        except ValueError:
            return _error(400, "Parameter 'limit' must be an integer")
        limit = min(limit, doc_server.config.get("search", {}).get("max_limit", 50))
        results = doc_server._search_docs(query, component, limit)
        return JSONResponse({"query": query, "component": component, "results": results})

    async def examples(request: Request) -> JSONResponse:
        query = request.query_params.get("query")
        if not query:
            return _error(400, "Missing required parameter: query")
        component = request.query_params.get("component")
        language = request.query_params.get("language")
        try:
            limit = int(request.query_params.get("limit", 10))
        except ValueError:
            return _error(400, "Parameter 'limit' must be an integer")
        limit = min(limit, doc_server.config.get("search", {}).get("max_limit", 50))
        results = doc_server._search_examples(query, component, language, limit)
        return JSONResponse({"query": query, "component": component, "language": language, "results": results})

    async def doc_page(request: Request) -> JSONResponse:
        source_file = request.path_params["source_file"]
        result = doc_server._get_doc_page(source_file)
        if "error" in result:
            return _error(404, result["error"])
        return JSONResponse(result)

    async def command_lookup(request: Request) -> JSONResponse:
        command = request.path_params["command"]
        result = doc_server._find_docs_for_command(command)
        return JSONResponse(result)

    async def components(request: Request) -> JSONResponse:
        return JSONResponse({"components": doc_server._list_components()})

    async def component_topics(request: Request) -> JSONResponse:
        component = request.path_params["component"]
        result = doc_server._list_topics(component)
        if "error" in result:
            return _error(404, result["error"])
        return JSONResponse(result)

    async def health(request: Request) -> JSONResponse:
        result = doc_server._health()
        status = 200 if result.get("status") == "ok" else 503
        return JSONResponse(result, status_code=status)

    async def capabilities(request: Request) -> JSONResponse:
        return JSONResponse(doc_server._capabilities())

    routes = [
        Route("/api/search", search),
        Route("/api/examples", examples),
        Route("/api/doc/{source_file:path}", doc_page),
        Route("/api/command/{command:path}", command_lookup),
        Route("/api/components", components),
        Route("/api/components/{component}/topics", component_topics),
        Route("/api/health", health),
        Route("/api/capabilities", capabilities),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET"],
            allow_headers=["*"],
        ),
    ]

    return Starlette(routes=routes, middleware=middleware)


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Ceph Documentation KB — REST API")
    parser.add_argument(
        "--kb-path",
        type=str,
        default=None,
        help="Path to knowledge base directory",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Index version to load (default: latest)",
    )
    parser.add_argument("--host", type=str, default=None, help="Bind host")
    parser.add_argument("--port", type=int, default=None, help="Bind port")

    args = parser.parse_args()

    config = _load_config()
    server_config = config.get("server", {})
    host = args.host or server_config.get("host", "127.0.0.1")
    port = args.port or server_config.get("port", 8100)

    app = create_app(kb_path=args.kb_path, version=args.version)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
