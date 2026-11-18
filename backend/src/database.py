import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,DeclarativeBase
url=os.getenv('DATABASE_URL','mysql+pymysql://solar:solar@db:3306/solar')
opts={'pool_pre_ping':True}
if not url.startswith('sqlite'):opts['isolation_level']='READ COMMITTED'
engine=create_engine(url,**opts)
Session=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase):pass
def session():
    with Session() as db:yield db
