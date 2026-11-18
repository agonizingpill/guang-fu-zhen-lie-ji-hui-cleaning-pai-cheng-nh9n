from datetime import date
from pydantic import Field,field_validator
from .revisit_schemas import Inputs
class StatementInput(Inputs):
    ref:str=Field(min_length=2,max_length=60)
    received_at:date
    amount:float=Field(gt=0,le=1000000)
    payer:str=Field(min_length=2,max_length=120)
    memo:str=Field(default='',max_length=200)
    @field_validator('ref','payer')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()
class AllocationItem(Inputs):
    statement_id:int
    settlement_id:int
    amount:float=Field(gt=0,le=1000000)
    note:str=Field(default='',max_length=200)
class BatchInput(Inputs):
    client_key:str=Field(min_length=4,max_length=80)
    note:str=Field(default='',max_length=200)
    allocations:list[AllocationItem]=Field(min_length=1,max_length=50)
    @field_validator('client_key')
    @classmethod
    def key_format(cls,v):
        v=v.strip()
        if len(v)<4:raise ValueError('批次键至少4位')
        return v
