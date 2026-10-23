import concurrent.futures
import re
import sqlite3
import time
from pathlib import Path
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from server import create_app, User, Order, Mail, LoginSession, Token, Rate, digest

@pytest.fixture
def app(tmp_path):
    app=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///'+str(tmp_path/'test.db'),'RATELIMIT_ENABLED':False,'MAIL_MODE':'local','PUBLIC_ORIGIN':'http://localhost','PRODUCTION':False})
    yield app
    app.extensions['db'].dispose()

def post(client,path,data=None,**headers):
    return client.post('/api'+path,json=data or {},headers={'X-Lamma-Request':'1',**headers})

def account(app,email,role='shop',verified=True):
    c=app.test_client()
    assert post(c,'/register',{'email':email,'password':'long-password-123','name':'Test Shop','role':role}).status_code==200
    if verified:
        with Session(app.extensions['db']) as db:
            mail=db.scalar(select(Mail).where(Mail.recipient==email).order_by(Mail.id.desc()))
            token=mail.body.split('#verify=')[1].split()[0]
        assert post(c,'/token/verify',{'token':token}).status_code==200
    return c

def add(c,**overrides):
    return post(c,'/orders',dict(area='Cairo',address='Street 12 Shop 4',weight=20,period='am',lat=30,lng=31,**overrides))

def test_complete_flow_race_and_permissions(app):
    shop=account(app,'shop@example.test');other=account(app,'other@example.test')
    c1=account(app,'one@example.test','collector');c2=account(app,'two@example.test','collector')
    assert add(c1).status_code==403
    oid=add(shop).json['id']
    assert other.get('/api/orders').json['orders']==[]
    public=c1.get('/api/orders').json['orders'][0]
    assert public['address']=='' and public['lat'] is None
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results=list(pool.map(lambda c:post(c,f'/orders/{oid}/book').status_code,[c1,c2]))
    assert sorted(results)==[200,409]
    winner,loser=(c1,c2) if results[0]==200 else (c2,c1)
    assert winner.get('/api/orders').json['orders'][0]['lat']==30
    assert post(loser,f'/orders/{oid}/receipt',{'actual':19,'price':5}).status_code==403
    assert post(shop,f'/orders/{oid}/cancel').status_code==409
    assert post(winner,f'/orders/{oid}/receipt',{'actual':float('nan'),'price':5}).status_code==400
    assert post(winner,f'/orders/{oid}/receipt',{'actual':19,'price':5}).status_code==200
    assert shop.get('/api/stats').json['value']==0
    assert post(other,f'/orders/{oid}/confirm').status_code==403
    assert post(shop,f'/orders/{oid}/reject').status_code==200
    assert post(winner,f'/orders/{oid}/receipt',{'actual':18,'price':5}).status_code==200
    assert post(shop,f'/orders/{oid}/confirm').status_code==200
    assert shop.get('/api/stats').json['value']==90
    assert post(winner,f'/orders/{oid}/release').status_code==409

def test_verification_recovery_revokes_sessions(app):
    c=account(app,'reset@example.test',verified=False)
    assert add(c).status_code==403
    assert post(c,'/forgot',{'email':'reset@example.test'}).json==post(c,'/forgot',{'email':'missing@example.test'}).json
    with Session(app.extensions['db']) as db:
        mail=db.scalar(select(Mail).where(Mail.recipient=='reset@example.test').order_by(Mail.id.desc()))
        token=mail.body.split('#reset=')[1].split()[0]
        assert db.get(Token,digest(token)) is not None
        assert db.get(Token,token) is None
    assert post(c,'/token/reset',{'token':token,'password':'new-password-456'}).status_code==200
    assert c.get('/api/me').json['user'] is None
    assert post(c,'/token/reset',{'token':token,'password':'new-password-789'}).status_code==400
    assert post(c,'/login',{'email':'reset@example.test','password':'long-password-123'}).status_code==401
    assert post(c,'/login',{'email':'reset@example.test','password':'new-password-456'}).status_code==200

def test_security_headers_csrf_body_host_and_private_files(app):
    c=app.test_client()
    response=c.get('/')
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert response.headers['X-Frame-Options']=='DENY'
    assert c.post('/api/login',json={}).status_code==403
    assert post(c,'/login',{},Origin='https://evil.example').status_code==403
    assert c.post('/api/login',data='x'*20000,headers={'X-Lamma-Request':'1','Content-Type':'application/json'}).status_code==413
    for path in ['/server.py','/data/lamma.db','/.env','/../server.py']:
        assert c.get(path).status_code==404
    app.config['TESTING']=False
    assert c.get('/',headers={'Host':'evil.example'}).status_code==400

def test_rate_limit_persists_between_clients(app):
    app.config['RATELIMIT_ENABLED']=True
    for _ in range(10):
        assert post(app.test_client(),'/login',{'email':'none@example.test','password':'invalid-password'}).status_code==401
    response=post(app.test_client(),'/login',{'email':'none@example.test','password':'invalid-password'})
    assert response.status_code==429 and 'Retry-After' in response.headers

def test_pagination_and_stats_over_all_records(app):
    c=account(app,'pages@example.test')
    with Session(app.extensions['db']) as db:
        uid=db.scalar(select(User.id))
        db.add_all([Order(shop_id=uid,area='Cairo',address='Test address',weight=20,period='am',status='done',actual=2,price=3) for _ in range(65)])
        db.commit()
    first=c.get('/api/orders?limit=30&view=history').json
    second=c.get('/api/orders?limit=30&view=history&before='+str(first['next_cursor'])).json
    assert len(first['orders'])==len(second['orders'])==30
    assert not ({o['id'] for o in first['orders']}&{o['id'] for o in second['orders']})
    assert c.get('/api/stats').json['value']==390

def test_sessions_expire_and_logout_everywhere(app):
    c=account(app,'session@example.test')
    second=app.test_client()
    assert post(second,'/login',{'email':'session@example.test','password':'long-password-123'}).status_code==200
    assert post(c,'/logout-all').status_code==200
    assert second.get('/api/me').json['user'] is None
    post(c,'/login',{'email':'session@example.test','password':'long-password-123'})
    with Session(app.extensions['db']) as db:
        db.execute(update(LoginSession).values(last_seen=time.time()-1900));db.commit()
    assert c.get('/api/me').json['user'] is None

def test_production_configuration_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):create_app({'PRODUCTION':True,'MAIL_MODE':'local','PUBLIC_ORIGIN':'http://localhost'})

def test_legacy_database_migration(tmp_path):
    path=tmp_path/'old.db'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,email TEXT UNIQUE,password TEXT,role TEXT); CREATE TABLE sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires REAL); CREATE TABLE orders(id INTEGER PRIMARY KEY,shop_id INTEGER,collector_id INTEGER,area TEXT,address TEXT,weight REAL,period TEXT,status TEXT,actual REAL,price REAL,created REAL);')
        db.execute("INSERT INTO users VALUES(1,'Existing','old@example.test','unused','shop')")
    migrated=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///'+str(path),'PRODUCTION':False})
    with Session(migrated.extensions['db']) as db:
        u=db.get(User,1);assert u.name=='Existing' and u.verified==0
    migrated.extensions['db'].dispose()
# PostgreSQL integration is executed in CI against a disposable service database.
import os
@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='PostgreSQL service not available locally')
def test_postgresql_atomic_booking():
    import uuid
    app=create_app({'TESTING':True,'DATABASE_URL':os.environ['TEST_POSTGRES_URL'],'RATELIMIT_ENABLED':False,'MAIL_MODE':'local','PRODUCTION':False})
    suffix=uuid.uuid4().hex
    shop=account(app,'s'+suffix+'@example.test')
    collectors=[account(app,str(i)+suffix+'@example.test','collector') for i in range(2)]
    oid=add(shop).json['id']
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results=list(pool.map(lambda c:post(c,f'/orders/{oid}/book').status_code,collectors))
    assert sorted(results)==[200,409]
    app.extensions['db'].dispose()
def test_backup_restore_and_no_overwrite(app,tmp_path):
    import subprocess,sys
    account(app,'backup@example.test')
    env=dict(os.environ,DATABASE_URL=app.config['DATABASE_URL'],LAMMA_ENV='development',MAIL_MODE='local')
    backup=tmp_path/'backup.db';restored=tmp_path/'restored.db'
    for command in [('backup',str(backup)),('restore',str(backup),str(restored))]:
        result=subprocess.run([sys.executable,str(Path(__file__).parent/'manage.py'),*command],env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    with sqlite3.connect(restored) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0]==1
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    result=subprocess.run([sys.executable,str(Path(__file__).parent/'manage.py'),'backup',str(backup)],env=env,capture_output=True)
    assert result.returncode!=0

def test_production_cookie_and_hsts(tmp_path,monkeypatch):
    monkeypatch.setenv('SMTP_HOST','smtp.example.test');monkeypatch.setenv('SMTP_FROM','lamma@example.test')
    app=create_app({'TESTING':True,'DATABASE_URL':'sqlite:///'+str(tmp_path/'prod.db'),'PRODUCTION':True,'PUBLIC_ORIGIN':'https://lamma.example.test','MAIL_MODE':'smtp','REQUIRE_VERIFICATION':True,'RATELIMIT_ENABLED':False})
    response=post(app.test_client(),'/register',{'name':'Test','email':'prod@example.test','password':'production-test-password','role':'shop'})
    assert response.status_code==200
    cookie=response.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    assert response.headers['Strict-Transport-Security']=='max-age=31536000'
    app.extensions['db'].dispose()
