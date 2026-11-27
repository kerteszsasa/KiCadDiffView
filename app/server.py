"""Same API through FastAPI or a dependency-free local development adapter."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import traceback
from urllib.parse import parse_qs, unquote, urlsplit

from .engine import Application

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 65536
SECURITY_HEADERS = {
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
}


def application_from_environment():
    roots = [p for p in os.environ.get('KICADDIFFVIEW_REPO_ROOTS', '/home/kerteszs/hw').split(os.pathsep) if p]
    return Application(roots, os.environ.get('KICADDIFFVIEW_DATA', str(ROOT/'data')))


def _hostname(value):
    if value.startswith('[') and value.endswith(']'):
        address = ipaddress.IPv6Address(value[1:-1])
        return str(address)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        name = value.removesuffix('.').encode('idna').decode('ascii').lower()
    except UnicodeError as error:
        raise ValueError('Invalid hostname.') from error
    label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if len(name) > 253 or not re.fullmatch(label+r'(?:\.'+label+r')*', name):
        raise ValueError('Invalid hostname.')
    return name


def check_host(host):
    try:
        if not host or any(char.isspace() for char in host):
            raise ValueError('Empty or whitespace-containing host.')
        parsed = urlsplit('//'+host)
        if (parsed.username is not None or parsed.password is not None or
                parsed.path or parsed.query or parsed.fragment or not parsed.hostname):
            raise ValueError('Invalid authority.')
        if parsed.port is not None and parsed.port < 1:
            raise ValueError('Invalid port.')
        _hostname(parsed.hostname)
    except ValueError as error:
        raise ValueError('Invalid Host header.') from error


def check_origin(origin, host):
    check_host(host)
    if origin and urlsplit(origin).netloc != host:
        raise ValueError('Cross-origin changes to the application are not allowed.')


def read_body(raw, content_type):
    if len(raw) > MAX_BODY:
        raise ValueError('The request is too large.')
    if not content_type.lower().startswith('application/json'):
        raise ValueError('A JSON request is required.')
    data = json.loads(raw or b'{}')
    if not isinstance(data, dict):
        raise ValueError('The request must be a JSON object.')
    return data


def file_for(application, path):
    if path.startswith('/results/'):
        parts = path.removeprefix('/results/').split('/',1)
        if len(parts) != 2:
            raise FileNotFoundError('Image not found.')
        return application.asset(parts[0], parts[1])
    root = ROOT/'frontend/dist'
    file = (root/('index.html' if path == '/' else path.lstrip('/'))).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise FileNotFoundError('File not found. Build the frontend with: node scripts/build-frontend.cjs')
    return file


def serve_native(application, host, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.handle_request()

        def do_HEAD(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def do_DELETE(self):
            self.handle_request()

        def handle_request(self):
            try:
                check_host(self.headers.get('Host'))
                parsed = urlsplit(self.path)
                path = unquote(parsed.path)
                method = 'GET' if self.command == 'HEAD' else self.command
                body = None
                if method in ('POST','DELETE'):
                    check_origin(self.headers.get('Origin'), self.headers.get('Host'))
                    length = int(self.headers.get('Content-Length','0'))
                    if not 0 <= length <= MAX_BODY:
                        raise ValueError('Invalid request size.')
                    if method == 'POST':
                        body = read_body(self.rfile.read(length), self.headers.get('Content-Type',''))
                if path.startswith('/api/'):
                    result = application.dispatch(method,path,parse_qs(parsed.query,keep_blank_values=True),body)
                    raw = json.dumps(result,ensure_ascii=False).encode()
                    mime = 'application/json; charset=utf-8'
                elif method == 'GET':
                    file = file_for(application,path)
                    raw = file.read_bytes()
                    mime = mimetypes.guess_type(file)[0] or 'application/octet-stream'
                else:
                    raise FileNotFoundError('Endpoint not found.')
                self.send(200,raw,mime)
            except (ValueError,UnicodeError) as error:
                self.send_error_json(400,str(error))
            except FileNotFoundError as error:
                self.send_error_json(404,str(error))
            except Exception:
                traceback.print_exc()
                self.send_error_json(500,'Internal error. See the server log for details.')

        def send_error_json(self,status,message):
            self.send(status,json.dumps({'error':message},ensure_ascii=False).encode(),'application/json; charset=utf-8')

        def send(self,status,raw,mime):
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(raw)))
            for key,value in SECURITY_HEADERS.items():
                self.send_header(key,value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(raw)

    server = ThreadingHTTPServer((host,port),Handler)
    print(f'KiCadDiffView: http://{host}:{port} (local Python HTTP adapter)',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.close()


def create_asgi(application):
    import asyncio
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse
    api = FastAPI(title='KiCadDiffView')

    @api.middleware('http')
    async def trusted_host(request: Request, call_next):
        try:
            check_host(request.headers.get('host'))
        except ValueError as error:
            return JSONResponse({'error':str(error)},status_code=400,headers=SECURITY_HEADERS)
        return await call_next(request)

    @api.api_route('/api/{path:path}',methods=['GET','POST','DELETE'])
    async def endpoint(path: str, request: Request):
        try:
            body = None
            if request.method in ('POST','DELETE'):
                check_origin(request.headers.get('origin'),request.headers.get('host'))
                if request.method == 'POST':
                    body = read_body(await request.body(),request.headers.get('content-type',''))
            query = parse_qs(request.url.query,keep_blank_values=True)
            result = await asyncio.to_thread(application.dispatch,request.method,'/api/'+path,query,body)
            return JSONResponse(result,headers=SECURITY_HEADERS)
        except (ValueError,UnicodeError) as error:
            return JSONResponse({'error':str(error)},status_code=400,headers=SECURITY_HEADERS)
        except FileNotFoundError as error:
            return JSONResponse({'error':str(error)},status_code=404,headers=SECURITY_HEADERS)

    @api.get('/{path:path}')
    async def files(path: str):
        try:
            return FileResponse(file_for(application,'/'+path),headers=SECURITY_HEADERS)
        except (ValueError,FileNotFoundError) as error:
            return JSONResponse({'error':str(error)},status_code=404,headers=SECURITY_HEADERS)

    @api.on_event('shutdown')
    def shutdown():
        application.close()
    return api


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--native',action='store_true',help='Standard-library development HTTP adapter')
    args = parser.parse_args()
    application = application_from_environment()
    if not args.native:
        try:
            import uvicorn
            api = create_asgi(application)
        except ImportError:
            pass
        else:
            uvicorn.run(api,host=args.host,port=args.port)
            return
    serve_native(application,args.host,args.port)


if __name__ == '__main__':
    main()
