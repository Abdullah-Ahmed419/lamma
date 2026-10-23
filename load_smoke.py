"""Repeatable local smoke benchmark; not a production capacity claim."""
import concurrent.futures
import http.cookiejar
import json
import statistics
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from sqlalchemy.orm import Session
from waitress import create_server
from server import create_app, User, Order, password_hash

def main():
    with tempfile.TemporaryDirectory() as tmp:
        app=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///'+str(Path(tmp)/'bench.db'),'RATELIMIT_ENABLED':False,'PRODUCTION':False,'MAIL_MODE':'local'})
        with Session(app.extensions['db']) as db:
            u=User(name='Load test',email='load@example.test',password=password_hash('load-test-password'),role='shop',verified=1);db.add(u);db.flush()
            db.add_all([Order(shop_id=u.id,area='Cairo',address='Synthetic address',weight=20,period='am',status='done',actual=18,price=5) for _ in range(5000)]);db.commit()
        http=create_server(app,host='127.0.0.1',port=0,threads=8)
        thread=threading.Thread(target=http.run,daemon=True);thread.start()
        base=f'http://127.0.0.1:{http.effective_port}'
        jar=__import__('http.cookiejar',fromlist=['CookieJar']).CookieJar()
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        client.open(urllib.request.Request(base+'/api/login',data=json.dumps({'email':'load@example.test','password':'load-test-password'}).encode(),headers={'Content-Type':'application/json','X-Lamma-Request':'1'})).close()
        cookie='; '.join(f'{c.name}={c.value}' for c in jar)
        def one(i):
            start=time.perf_counter()
            with urllib.request.urlopen(urllib.request.Request(base+('/api/stats' if i%2 else '/api/orders?limit=30'),headers={'Cookie':cookie}),timeout=10) as r:
                body=json.load(r);assert r.status==200
                if i%2:assert body['completed']==5000
                else:assert len(body['orders'])==30
            return (time.perf_counter()-start)*1000
        try:
            start=time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:times=list(pool.map(one,range(200)))
            duration=time.perf_counter()-start
            print(json.dumps({'records':5000,'requests':200,'concurrency':8,'failures':0,'seconds':round(duration,2),'requests_per_second':round(200/duration,1),'p95_ms':round(sorted(times)[189],1),'note':'Local synthetic smoke test; rate limiting disabled; not a production capacity guarantee'},indent=2))
        finally:
            http.close();http.task_dispatcher.shutdown();thread.join(timeout=2);app.extensions['db'].dispose()
if __name__=='__main__':main()
