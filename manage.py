"""Operator tools. Never expose this module through HTTP."""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from server import create_app, Mail, Token, Rate, LoginSession, deliver_mail

parser=argparse.ArgumentParser()
sub=parser.add_subparsers(dest='command',required=True)
sub.add_parser('mailbox',help='Show local development messages (contains private one-time links)')
sub.add_parser('mail-worker',help='Send queued SMTP messages; run a single worker')
sub.add_parser('cleanup',help='Remove expired sessions, tokens, counters and old messages')
b=sub.add_parser('backup');b.add_argument('destination',type=Path)
r=sub.add_parser('restore');r.add_argument('source',type=Path);r.add_argument('destination',type=Path)
args=parser.parse_args()
app=create_app()
engine=app.extensions['db']
if args.command=='mailbox':
    if app.config['MAIL_MODE']!='local' or app.config['PRODUCTION']:parser.error('Mailbox is available only in local development mode')
    with Session(engine) as db:
        for m in db.scalars(select(Mail).where(Mail.created>time.time()-86400).order_by(Mail.id.desc()).limit(20)):
            print(f'\nTo: {m.recipient}\n{m.subject}\n{m.body}')
elif args.command=='mail-worker':
    if app.config['MAIL_MODE']!='smtp':parser.error('Configure MAIL_MODE=smtp first')
    while True:
        deliver_mail(app);time.sleep(30)
elif args.command=='cleanup':
    with Session(engine) as db:
        now=time.time()
        db.execute(delete(LoginSession).where((LoginSession.expires<now)|(LoginSession.last_seen<now-1800)))
        db.execute(delete(Token).where(Token.expires<now))
        db.execute(delete(Rate).where(Rate.expires<now))
        db.execute(delete(Mail).where(Mail.created<now-86400))
        db.commit()
    print('Expired security records removed.')
elif args.command in ('backup','restore'):
    if engine.dialect.name!='sqlite':parser.error('Use pg_dump/pg_restore for PostgreSQL; see DEPLOYMENT.md')
    source=Path(engine.url.database) if args.command=='backup' else args.source
    target=args.destination.resolve()
    if target.exists():parser.error('Destination must not exist; existing data will not be overwritten')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{source.resolve().as_posix()}?mode=ro',uri=True) as src:
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':parser.error('Source database failed integrity check')
        with sqlite3.connect(target) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity check failed')
    print(f'Verified database copy created at {target}')
