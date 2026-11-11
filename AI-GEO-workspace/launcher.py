"""Windows Proactor event loop supports Playwright's browser subprocess."""
import argparse,asyncio,sys,logging,traceback
from logging.handlers import RotatingFileHandler
import uvicorn

async def serve_until_stopped(server,stop_file):
 async def observe_stop():
  while not server.should_exit:
   if stop_file.exists():
    logging.getLogger('ai_geo.desktop').info('Desktop stop requested; gracefully shutting down')
    server.should_exit=True
    return
   await asyncio.sleep(1)
 watcher=asyncio.create_task(observe_stop())
 try:await server.serve()
 finally:
  watcher.cancel()
  await asyncio.gather(watcher,return_exceptions=True)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8020);args=parser.parse_args()
 if sys.platform=='win32':asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
 from config import HOME
 folder=HOME/'logs';folder.mkdir(parents=True,exist_ok=True)
 handler=RotatingFileHandler(folder/'server.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
 handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
 logging.basicConfig(level=logging.INFO,handlers=[handler],force=True)
 config=uvicorn.Config('app:app',host='127.0.0.1',port=args.port,log_level='info',loop='asyncio',ws='none',access_log=False,log_config=None)
 from desktop_service import STOP
 asyncio.run(serve_until_stopped(uvicorn.Server(config),STOP))
if __name__=='__main__':
 try:main()
 except Exception:
  from config import HOME
  folder=HOME/'logs';folder.mkdir(parents=True,exist_ok=True)
  with (folder/'startup.log').open('a',encoding='utf-8') as output:traceback.print_exc(file=output)
  raise
