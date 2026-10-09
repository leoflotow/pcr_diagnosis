"""统一网页启动入口；默认本机访问，局域网由启动器显式开启。"""
import argparse
import os


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8501)
    parser.add_argument('--host',choices=['127.0.0.1','0.0.0.0'],default='127.0.0.1')
    parser.add_argument('--secrets-path')
    args=parser.parse_args()
    if args.secrets_path:os.environ['BIO_SECRETS_PATH']=args.secrets_path
    import uvicorn
    from teaching_platform.api import create_app
    uvicorn.run(create_app(),host=args.host,port=args.port,access_log=False,log_level='warning')


if __name__=='__main__':main()
