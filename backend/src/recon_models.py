from datetime import date,datetime
from sqlalchemy import String,Float,Integer,ForeignKey,JSON,CheckConstraint,UniqueConstraint,Date,DateTime,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base
class BankStatement(Base):
    __tablename__='bank_statements'
    __table_args__=(CheckConstraint('amount<>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    ref:Mapped[str]=mapped_column(String(60),unique=True)
    received_at:Mapped[date]=mapped_column(Date)
    amount:Mapped[float]=mapped_column(Float)
    payer:Mapped[str]=mapped_column(String(120))
    memo:Mapped[str]=mapped_column(String(200),default='')
    kind:Mapped[str]=mapped_column(String(16),default='receipt')
    state:Mapped[str]=mapped_column(String(24),default='unclaimed')
    allocated_amount:Mapped[float]=mapped_column(Float,default=0)
    reversal_of_id:Mapped[int|None]=mapped_column(ForeignKey('bank_statements.id'),nullable=True)
    # 逻辑指向recon_allocations.id；两表互引用，留整型避免外键成环，唯一约束保证重复冲正只生效一次
    reverses_allocation_id:Mapped[int|None]=mapped_column(Integer,unique=True,nullable=True)
    created_by:Mapped[str]=mapped_column(String(120),default='')
class ReconBatch(Base):
    __tablename__='recon_batches'
    id:Mapped[int]=mapped_column(primary_key=True)
    client_key:Mapped[str]=mapped_column(String(80),unique=True)
    source:Mapped[str]=mapped_column(String(16),default='manual')
    note:Mapped[str]=mapped_column(String(200),default='')
    state:Mapped[str]=mapped_column(String(24),default='open')
    created_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    confirmed_by:Mapped[str]=mapped_column(String(120),default='')
    confirmed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class ReconAllocation(Base):
    __tablename__='recon_allocations'
    __table_args__=(UniqueConstraint('batch_id','statement_id','settlement_id'),CheckConstraint('amount>0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    batch_id:Mapped[int]=mapped_column(ForeignKey('recon_batches.id'))
    statement_id:Mapped[int]=mapped_column(ForeignKey('bank_statements.id'))
    settlement_id:Mapped[int]=mapped_column(ForeignKey('wash_settlements.id'))
    amount:Mapped[float]=mapped_column(Float)
    source:Mapped[str]=mapped_column(String(16),default='manual')
    basis:Mapped[dict]=mapped_column(JSON,default=dict)
    state:Mapped[str]=mapped_column(String(24),default='pending')
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    confirmed_by:Mapped[str]=mapped_column(String(120),default='')
    confirmed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    reversed_by:Mapped[str]=mapped_column(String(120),default='')
    reversed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
