from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .recon_models import BankStatement,ReconBatch,ReconAllocation
from .recon_schemas import StatementInput,BatchInput
from . import recon_service
router=APIRouter()
@router.get('/recon/statements')
def statements(u=Depends(current),db=Depends(session)):return db.scalars(select(BankStatement).order_by(BankStatement.id.desc())).all()
@router.post('/recon/statements')
def register(b:StatementInput,u=Depends(editor),db=Depends(session)):return recon_service.register_statement(db,b,u)
@router.get('/recon/batches')
def batches(u=Depends(current),db=Depends(session)):return db.scalars(select(ReconBatch).order_by(ReconBatch.id.desc())).all()
@router.post('/recon/batches')
def create(b:BatchInput,u=Depends(editor),db=Depends(session)):return recon_service.create_batch(db,b,u)
@router.post('/recon/batches/{key}/confirm')
def confirm(key:int,u=Depends(admin),db=Depends(session)):return recon_service.confirm_batch(db,key,u)
@router.post('/recon/batches/{key}/discard')
def discard(key:int,u=Depends(editor),db=Depends(session)):return recon_service.discard_batch(db,key,u)
@router.get('/recon/allocations')
def allocations(u=Depends(current),db=Depends(session)):return db.scalars(select(ReconAllocation).order_by(ReconAllocation.id.desc())).all()
@router.post('/recon/allocations/{key}/reverse')
def reverse(key:int,u=Depends(admin),db=Depends(session)):return recon_service.reverse_allocation(db,key,u)
@router.get('/recon/matcher')
def matcher(u=Depends(current),db=Depends(session)):return recon_service.matcher_status(db)
@router.post('/recon/suggest')
def suggest(u=Depends(editor),db=Depends(session)):return recon_service.suggest(db,u)
