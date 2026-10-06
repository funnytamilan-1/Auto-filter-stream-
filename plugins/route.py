from aiohttp import web
from database.users_chats_db import mydb

routes = web.RouteTableDef()

def _range_header(value, size):
    if not value or not value.startswith("bytes="): return None
    raw=value[6:].split(",",1)[0].strip()
    if "-" not in raw: return None
    a,b=raw.split("-",1)
    try:
        if a: start=int(a); end=int(b) if b else size-1
        else:
            length=int(b); start=max(0,size-length); end=size-1
        if start<0 or start>=size or end<start: return None
        return start,min(end,size-1)
    except ValueError: return None

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"ok":True,"service":"stream-bot"})

@routes.get("/watch/{token}", allow_head=True)
async def watch_route(request):
    token=request.match_info["token"]
    doc=await mydb.stream_links.find_one({"token":token,"active":True})
    if not doc: raise web.HTTPNotFound(text="Stream not found")
    title=str(doc.get("title") or "Video").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html=f"""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>html,body{{margin:0;background:#08090d;color:#fff;font-family:system-ui}}main{{max-width:1100px;margin:auto;padding:18px}}.p{{background:#000;border-radius:16px;overflow:hidden}}video{{width:100%;max-height:78vh;background:#000;display:block}}h2{{font-size:18px}}small{{color:#9aa1b2}}</style></head>
<body><main><div class="p"><video controls playsinline preload="metadata" src="/stream/{token}"></video></div><h2>{title}</h2><small>JustDot Stream • Fast range playback</small></main></body></html>"""
    return web.Response(text=html,content_type="text/html")

@routes.get("/stream/{token}")
async def stream_route(request):
    token=request.match_info["token"]
    doc=await mydb.stream_links.find_one({"token":token,"active":True})
    if not doc: raise web.HTTPNotFound(text="Stream not found")
    size=int(doc.get("size") or 0)
    if size<=0: raise web.HTTPNotFound(text="File size unavailable")
    bot=request.app["bot"]
    try: message=await bot.get_messages(int(doc["chat_id"]),int(doc["message_id"]))
    except Exception: raise web.HTTPNotFound(text="Telegram source unavailable")
    media=message.video or message.document
    if not media: raise web.HTTPNotFound(text="Media unavailable")
    requested=_range_header(request.headers.get("Range"),size)
    start,end=requested or (0,size-1); length=end-start+1
    response=web.StreamResponse(status=206 if requested else 200,headers={"Content-Type":doc.get("mime") or getattr(media,"mime_type",None) or "application/octet-stream","Accept-Ranges":"bytes","Content-Length":str(length),"Cache-Control":"public, max-age=60"})
    if requested: response.headers["Content-Range"]=f"bytes {start}-{end}/{size}"
    await response.prepare(request)
    skip=start//(1024*1024); offset=start%(1024*1024); remaining=length
    try:
        async for chunk in bot.stream_media(message):
            if skip: skip-=1; continue
            if offset: chunk=chunk[offset:]; offset=0
            if not chunk: continue
            if len(chunk)>remaining: chunk=chunk[:remaining]
            await response.write(chunk); remaining-=len(chunk)
            if remaining<=0: break
    except Exception: pass
    try: await response.write_eof()
    except Exception: pass
    await mydb.stream_links.update_one({"token":token},{"$inc":{"views":1}})
    return response
