"""Lamma application: Flask + SQLAlchemy, served by Waitress."""
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import smtplib
import ssl
import time
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, request, jsonify, send_from_directory, g
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, Index, select, update, delete, func, event, inspect, text
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
Base = declarative_base()
log = logging.getLogger('lamma')
class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True)
    name=Column(String(60),nullable=False)
    email=Column(String(200),unique=True,nullable=False)
    password=Column(String(200),nullable=False)
    role=Column(String(16),nullable=False)
    verified=Column(Integer,nullable=False,default=0,server_default='0')
class LoginSession(Base):
    __tablename__='sessions'
    token=Column(String(64),primary_key=True)
    user_id=Column(Integer,ForeignKey('users.id'),nullable=False,index=True)
    expires=Column(Float,nullable=False,index=True)
    last_seen=Column(Float,nullable=False,default=time.time,server_default='0')
    credential=Column(String(64),nullable=False,default='',server_default='')
class Order(Base):
    __tablename__='orders'
    id=Column(Integer,primary_key=True)
    shop_id=Column(Integer,ForeignKey('users.id'),nullable=False)
    collector_id=Column(Integer,ForeignKey('users.id'))
    area=Column(String(80)); address=Column(String(300)); weight=Column(Float)
    period=Column(String(8)); status=Column(String(16),default='new'); actual=Column(Float); price=Column(Float)
    created=Column(Float,default=time.time)
    lat=Column(Float); lng=Column(Float)
    __table_args__=(Index('ix_orders_shop_id_id','shop_id','id'),Index('ix_orders_collector_id_id','collector_id','id'),Index('ix_orders_status_id','status','id'))
class Audit(Base):
    __tablename__='events'
    id=Column(Integer,primary_key=True);order_id=Column(Integer);user_id=Column(Integer);action=Column(String(40));created=Column(Float,default=time.time)
class Token(Base):
    __tablename__='action_tokens'
    token=Column(String(64),primary_key=True);user_id=Column(Integer,ForeignKey('users.id'));purpose=Column(String(16));expires=Column(Float,index=True)
class Rate(Base):
    __tablename__='rate_limits'
    key=Column(String(64),primary_key=True);count=Column(Integer,nullable=False);expires=Column(Float,index=True)
class Mail(Base):
    __tablename__='mail_queue'
    id=Column(Integer,primary_key=True);recipient=Column(String(200));subject=Column(String(200));body=Column(String(5000));created=Column(Float,default=time.time);attempts=Column(Integer,default=0);sent=Column(Float)

class Problem(Exception):
    def __init__(self,status,ar,en):self.status,self.ar,self.en=status,ar,en

def need(ok,ar,en,status=400):
    if not ok:raise Problem(status,ar,en)
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
DUMMY=password_hash('constant-dummy-password')
def verify(password,encoded):return hmac.compare_digest(encoded,password_hash(password,encoded.split(':')[0]))
def numeric(data,key,low,high):
    try:v=float(data[key])
    except (ValueError,TypeError,KeyError):raise Problem(400,'أدخل قيمة رقمية صحيحة','Enter a valid number')
    need(math.isfinite(v) and low<=v<=high,'القيمة خارج الحدود المسموحة','Value is outside allowed limits')
    return v

def create_app(config=None):
    app=Flask(__name__,static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=16384,PRODUCTION=os.getenv('LAMMA_ENV')=='production',PUBLIC_ORIGIN=os.getenv('PUBLIC_ORIGIN','http://127.0.0.1:8002'),DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///'+str(ROOT/'data'/'lamma.db').replace('\\','/')),MAIL_MODE=os.getenv('MAIL_MODE','local'),REQUIRE_VERIFICATION=os.getenv('REQUIRE_VERIFICATION','1')=='1',RATELIMIT_ENABLED=True)
    if config:app.config.update(config)
    origin=app.config['PUBLIC_ORIGIN'].rstrip('/')
    if app.config['PRODUCTION']:
        if not origin.startswith('https://') or app.config['MAIL_MODE']!='smtp' or not app.config['REQUIRE_VERIFICATION']:
            raise RuntimeError('Production requires HTTPS PUBLIC_ORIGIN, MAIL_MODE=smtp and verification enabled')
        if not os.getenv('SMTP_HOST') or not os.getenv('SMTP_FROM'):
            raise RuntimeError('Production requires SMTP_HOST and SMTP_FROM')
    ROOT.joinpath('data').mkdir(exist_ok=True)
    sqlite=app.config['DATABASE_URL'].startswith('sqlite:')
    engine=create_engine(app.config['DATABASE_URL'],pool_pre_ping=True,**({'connect_args':{'timeout':15}} if sqlite else {'pool_size':10,'max_overflow':10,'pool_timeout':10}))
    if sqlite:
        @event.listens_for(engine,'connect')
        def sqlite_setup(dbapi,_):
            dbapi.execute('PRAGMA foreign_keys=ON');dbapi.execute('PRAGMA journal_mode=WAL');dbapi.execute('PRAGMA busy_timeout=15000')
    app.extensions['db']=engine
    Base.metadata.create_all(engine)
    # Additive migration from the first local MVP. Existing accounts must verify email.
    with engine.begin() as conn:
        for table,columns in {'users':{'verified':'INTEGER NOT NULL DEFAULT 0'},'sessions':{'last_seen':'FLOAT NOT NULL DEFAULT 0','credential':"VARCHAR(64) NOT NULL DEFAULT ''"},'orders':{'lat':'FLOAT','lng':'FLOAT'}}.items():
            existing={c['name'] for c in inspect(conn).get_columns(table)}
            for name,ddl in columns.items():
                if name not in existing:conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
        # Existing-table create_all does not create new indexes.
        for table in Base.metadata.tables.values():
            for index in table.indexes:index.create(conn,checkfirst=True)

    def rate(key,limit,seconds):
        if not app.config['RATELIMIT_ENABLED']:return
        bucket=int(time.time()//seconds)
        key=digest(f'{key}:{bucket}')
        with Session(engine) as db:
            # Dialect-specific upsert provides an atomic counter across processes.
            if sqlite:from sqlalchemy.dialects.sqlite import insert
            else:from sqlalchemy.dialects.postgresql import insert
            statement=insert(Rate).values(key=key,count=1,expires=(bucket+1)*seconds)
            count=db.execute(statement.on_conflict_do_update(index_elements=['key'],set_={'count':Rate.count+1}).returning(Rate.count)).scalar_one()
            db.commit()
        need(count<=limit,'محاولات كثيرة؛ انتظر قليلًا ثم حاول مرة أخرى','Too many attempts. Please wait and try again.',429)

    @app.before_request
    def before():
        g.request_id=uuid.uuid4().hex
        if not app.config.get('TESTING'):
            need(request.host==urlsplit(origin).netloc,'عنوان خادم غير مسموح','Unrecognized host',400)
        if request.path.startswith('/api/'):
            rate('all:'+request.remote_addr,300,60)
        if request.method=='POST':
            need(request.headers.get('X-Lamma-Request')=='1','طلب غير مسموح','Request denied',403)
            need(request.headers.get('Origin') in (None,origin),'مصدر غير مسموح','Origin denied',403)
            need(request.headers.get('Sec-Fetch-Site')!='cross-site','طلب غير مسموح','Cross-site request denied',403)
            need(request.mimetype=='application/json','نوع بيانات غير مسموح','JSON required',415)
        g.db=Session(engine)
        g.user=None
        token=request.cookies.get('lamma_session','')
        if token:
            s=g.db.get(LoginSession,digest(token))
            if s and s.expires>time.time() and s.last_seen>time.time()-1800:
                candidate=g.db.get(User,s.user_id)
                g.user=candidate if candidate and hmac.compare_digest(s.credential,digest(candidate.password)) else None
                if s.last_seen<time.time()-60:
                    s.last_seen=time.time();g.db.commit()
    @app.teardown_request
    def teardown(error):
        if 'db' in g:g.db.close()
    @app.after_request
    def headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store','Permissions-Policy':'camera=(), microphone=(), geolocation=(self)','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'X-Request-ID':getattr(g,'request_id','')})
        if app.config['PRODUCTION']:response.headers['Strict-Transport-Security']='max-age=31536000'
        if response.status_code==429:response.headers['Retry-After']='900'
        return response
    @app.errorhandler(Problem)
    def problem(e):return jsonify(error=e.en if request.headers.get('Accept-Language','').startswith('en') else e.ar),e.status
    @app.errorhandler(HTTPException)
    def http_error(e):return jsonify(error=e.name),e.code
    @app.errorhandler(Exception)
    def unknown(e):
        log.error('request_failed id=%s type=%s',getattr(g,'request_id',''),type(e).__name__)
        return jsonify(error='Service temporarily unavailable',request_id=getattr(g,'request_id','')),503 if isinstance(e,OperationalError) else 500
    def data():
        value=request.get_json()
        need(isinstance(value,dict),'بيانات غير صحيحة','Invalid body')
        return value
    def auth(role=None,verified=False):
        need(g.user is not None,'سجّل الدخول أولًا','Please sign in',401)
        need(role is None or g.user.role==role,'ليس لديك صلاحية','Access denied',403)
        if verified and app.config['REQUIRE_VERIFICATION']:
            need(g.user.verified,'أكد بريدك الإلكتروني أولًا','Verify your email first',403)
        return g.user
    def new_token(user,purpose):
        token=secrets.token_urlsafe(32)
        g.db.execute(delete(Token).where(Token.user_id==user.id,Token.purpose==purpose))
        g.db.add(Token(token=digest(token),user_id=user.id,purpose=purpose,expires=time.time()+(1800 if purpose=='reset' else 86400)))
        link=origin+'/#'+purpose+'='+token
        g.db.add(Mail(recipient=user.email,subject='Lamma | '+('Reset password' if purpose=='reset' else 'Verify email'),body='لَمّة / Lamma\n\n'+link+'\n\nIgnore this message if you did not request it.'))
    def session_response(uid,credential):
        old=request.cookies.get('lamma_session','')
        if old:g.db.execute(delete(LoginSession).where(LoginSession.token==digest(old)))
        token=secrets.token_urlsafe(32)
        g.db.add(LoginSession(token=digest(token),user_id=uid,expires=time.time()+86400,last_seen=time.time(),credential=digest(credential)))
        g.db.commit()
        response=jsonify(ok=True)
        response.set_cookie('lamma_session',token,max_age=86400,httponly=True,secure=app.config['PRODUCTION'],samesite='Strict',path='/')
        return response
    def credentials(d):
        email=str(d.get('email','')).strip().lower();password=d.get('password','')
        need(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) is not None and len(email)<=200,'أدخل بريدًا صحيحًا','Enter a valid email')
        need(isinstance(password,str) and 10<=len(password)<=128,'كلمة المرور من 10 إلى 128 حرفًا','Password must be 10–128 characters')
        return email,password

    @app.get('/api/health')
    def health():
        g.db.execute(text('SELECT 1'))
        return jsonify(status='ok')
    @app.get('/api/me')
    def me():
        u=g.user
        return jsonify(user={'id':u.id,'name':u.name,'email':u.email,'role':u.role,'verified':bool(u.verified)} if u else None,mail_mode=app.config['MAIL_MODE'])
    @app.post('/api/register')
    def register():
        rate('register:'+request.remote_addr,5,3600)
        d=data();email,password=credentials(d)
        name=str(d.get('name','')).strip();role=d.get('role')
        need(2<=len(name)<=60 and role in ('shop','collector'),'راجع الاسم ونوع الحساب','Check name and account type')
        u=User(name=name,email=email,password=password_hash(password),role=role,verified=0)
        try:
            g.db.add(u);g.db.flush();new_token(u,'verify')
            return session_response(u.id,u.password)
        except IntegrityError:
            g.db.rollback();raise Problem(409,'تعذر إنشاء الحساب؛ جرّب تسجيل الدخول أو استعادة كلمة المرور','Cannot create account. Try signing in or password recovery.')
    @app.post('/api/login')
    def login():
        d=data();email,password=credentials(d)
        rate('login-ip:'+request.remote_addr,30,900);rate('login-account:'+email,10,900)
        u=g.db.scalar(select(User).where(User.email==email))
        valid=verify(password,u.password if u else DUMMY)
        need(u is not None and valid,'البريد أو كلمة المرور غير صحيحة','Invalid email or password',401)
        return session_response(u.id,u.password)
    @app.post('/api/logout')
    def logout():
        auth();g.db.execute(delete(LoginSession).where(LoginSession.token==digest(request.cookies.get('lamma_session',''))));g.db.commit()
        r=jsonify(ok=True);r.delete_cookie('lamma_session',path='/',secure=app.config['PRODUCTION'],httponly=True,samesite='Strict');return r
    @app.post('/api/logout-all')
    def logout_all():
        u=auth();g.db.execute(delete(LoginSession).where(LoginSession.user_id==u.id));g.db.commit()
        r=jsonify(ok=True);r.delete_cookie('lamma_session',path='/');return r
    @app.post('/api/forgot')
    def forgot():
        d=data();email=str(d.get('email','')).strip().lower()
        rate('recovery-ip:'+request.remote_addr,10,3600);rate('recovery-email:'+email,3,3600)
        u=g.db.scalar(select(User).where(User.email==email))
        if u:new_token(u,'reset');g.db.commit()
        return jsonify(ok=True)
    @app.post('/api/resend')
    def resend():
        u=auth();rate('verify:'+str(u.id),3,3600)
        if not u.verified:new_token(u,'verify');g.db.commit()
        return jsonify(ok=True)
    @app.post('/api/token/<purpose>')
    def consume(purpose):
        need(purpose in ('verify','reset'),'غير موجود','Not found',404)
        rate('tokens:'+request.remote_addr,20,900)
        d=data();token=str(d.get('token',''))
        new_password=d.get('password','')
        encoded=None
        if purpose=='reset':
            need(isinstance(new_password,str) and 10<=len(new_password)<=128,'كلمة المرور من 10 إلى 128 حرفًا','Password must be 10–128 characters')
            encoded=password_hash(new_password)
        found=g.db.execute(delete(Token).where(Token.token==digest(token),Token.purpose==purpose,Token.expires>time.time()).returning(Token.user_id)).scalar_one_or_none()
        need(found is not None,'الرابط غير صالح أو انتهت صلاحيته','Invalid or expired link',400)
        if purpose=='verify':g.db.execute(update(User).where(User.id==found).values(verified=1))
        else:
            g.db.execute(update(User).where(User.id==found).values(password=encoded))
            g.db.execute(delete(LoginSession).where(LoginSession.user_id==found))
            g.db.execute(delete(Token).where(Token.user_id==found,Token.purpose=='reset'))
        g.db.commit();return jsonify(ok=True)

    def scope(u):return Order.shop_id==u.id if u.role=='shop' else ((Order.status=='new')|(Order.collector_id==u.id))
    @app.get('/api/stats')
    def stats():
        u=auth();own=Order.shop_id==u.id if u.role=='shop' else Order.collector_id==u.id
        row=g.db.execute(select(func.count(),func.coalesce(func.sum(Order.actual),0),func.coalesce(func.sum(Order.actual*Order.price),0)).where(own,Order.status=='done')).one()
        active=g.db.scalar(select(func.count()).select_from(Order).where(own,Order.status.in_(['new','booked','pending'])))
        return jsonify(completed=row[0],weight=row[1],value=round(row[2],2),active=active)
    @app.get('/api/orders')
    def orders():
        u=auth();before=request.args.get('before',type=int);limit=min(max(request.args.get('limit',50,type=int),1),100)
        query=select(Order,User.name).join(User,User.id==Order.shop_id).where(scope(u))
        mode=request.args.get('view')
        if mode in ('active','history'):query=query.where(Order.status.in_(['new','booked','pending'] if mode=='active' else ['done','cancelled']))
        if before:query=query.where(Order.id<before)
        area=request.args.get('area','').strip()[:80]
        if area:query=query.where(Order.area.contains(area,autoescape=True))
        rows=g.db.execute(query.order_by(Order.id.desc()).limit(limit+1)).all()
        result=[]
        for o,name in rows[:limit]:
            visible=u.role=='shop' or o.collector_id==u.id
            item={c.name:getattr(o,c.name) for c in Order.__table__.columns};item['name']=name
            if not visible:item.update(address='',lat=None,lng=None)
            result.append(item)
        return jsonify(orders=result,next_cursor=result[-1]['id'] if len(rows)>limit else None)
    @app.post('/api/orders')
    def add_order():
        u=auth('shop',True);rate('new-order:'+str(u.id),30,3600)
        d=data();area=str(d.get('area','')).strip();address=str(d.get('address','')).strip()
        need(2<=len(area)<=80 and 5<=len(address)<=300,'أدخل المنطقة والعنوان التفصيلي','Enter area and full pickup address')
        need(d.get('period') in ('am','pm'),'اختر الفترة','Choose pickup period')
        lat=lng=None
        if d.get('lat') not in ('',None) or d.get('lng') not in ('',None):lat=numeric(d,'lat',-90,90);lng=numeric(d,'lng',-180,180)
        o=Order(shop_id=u.id,area=area,address=address,weight=numeric(d,'weight',1,5000),period=d['period'],lat=lat,lng=lng)
        g.db.add(o);g.db.flush();g.db.add(Audit(order_id=o.id,user_id=u.id,action='create'));g.db.commit()
        return jsonify(ok=True,id=o.id),201
    @app.post('/api/orders/<int:oid>/<action>')
    def change_order(oid,action):
        u=auth(verified=True);d=data();o=g.db.get(Order,oid)
        need(o is not None,'الطلب غير موجود','Order not found',404)
        values={};expected=None
        if action=='book':
            need(u.role=='collector','متاح للجامع فقط','Collectors only',403);expected='new';values={'status':'booked','collector_id':u.id}
        elif action in ('cancel','confirm','reject'):
            need(u.role=='shop' and o.shop_id==u.id,'ليس لديك صلاحية','Access denied',403)
            expected='new' if action=='cancel' else 'pending'
            values={'status':{'cancel':'cancelled','confirm':'done','reject':'booked'}[action]}
            if action=='reject':values.update(actual=None,price=None)
        elif action in ('release','receipt'):
            need(u.role=='collector' and o.collector_id==u.id,'ليس لديك صلاحية','Access denied',403);expected='booked'
            values={'status':'new','collector_id':None} if action=='release' else {'status':'pending','actual':numeric(d,'actual',.1,5000),'price':numeric(d,'price',0,10000)}
        else:raise Problem(404,'غير موجود','Not found')
        filters=[Order.id==oid,Order.status==expected]
        if action in ('release','receipt'):filters.append(Order.collector_id==u.id)
        changed=g.db.execute(update(Order).where(*filters).values(**values)).rowcount
        need(changed==1,'حالة الطلب اتغيرت؛ حدّث القائمة','Order changed. Refresh and try again.',409)
        g.db.add(Audit(order_id=oid,user_id=u.id,action=action));g.db.commit();return jsonify(ok=True)
    @app.get('/')
    def index():return send_from_directory(ROOT/'dist','index.html')
    @app.get('/<path:name>')
    def static(name):
        need(name in ('app.js','style.css','i18n.js'),'غير موجود','Not found',404)
        return send_from_directory(ROOT/'dist',name)
    return app

def deliver_mail(app):
    """Run periodically as a single worker. Local mode keeps messages for the CLI mailbox."""
    if app.config['MAIL_MODE']!='smtp':return 0
    delivered=0
    with Session(app.extensions['db']) as db:
        for mail in db.scalars(select(Mail).where(Mail.sent==None,Mail.attempts<5).order_by(Mail.id).limit(20)):
            mail.attempts+=1;db.commit()
            msg=EmailMessage();msg['From']=os.environ['SMTP_FROM'];msg['To']=mail.recipient;msg['Subject']=mail.subject;msg.set_content(mail.body)
            try:
                with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=15) as smtp:
                    smtp.starttls(context=ssl.create_default_context())
                    if os.getenv('SMTP_USER'):smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
                    smtp.send_message(msg)
                mail.sent=time.time();mail.body='[delivered]';db.commit();delivered+=1
            except (OSError,smtplib.SMTPException):log.warning('mail_delivery_failed id=%s',mail.id)
    return delivered

if __name__=='__main__':
    from waitress import serve
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    app=create_app()
    port=int(os.getenv('PORT','8002'))
    print(f'Lamma: http://127.0.0.1:{port}',flush=True)
    serve(app,host=os.getenv('BIND_HOST','127.0.0.1'),port=port,threads=8,connection_limit=100,channel_timeout=30,max_request_body_size=16384,clear_untrusted_proxy_headers=True)
