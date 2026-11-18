import uuid
from datetime import datetime
from sqlalchemy import select,func
from fastapi import HTTPException
from .operations_models import WashSettlement
from .recon_models import BankStatement,ReconBatch,ReconAllocation
from .field_service import require,audit
from . import match_model
EPS=0.004
def received_sum(db,settlement_id):
    return round(db.scalar(select(func.coalesce(func.sum(ReconAllocation.amount),0)).where(ReconAllocation.settlement_id==settlement_id,ReconAllocation.state=='confirmed')) or 0,2)
def pending_sum(db,settlement_id=None,statement_id=None):
    q=select(func.coalesce(func.sum(ReconAllocation.amount),0)).where(ReconAllocation.state=='pending')
    if settlement_id:q=q.where(ReconAllocation.settlement_id==settlement_id)
    if statement_id:q=q.where(ReconAllocation.statement_id==statement_id)
    return round(db.scalar(q) or 0,2)
def refresh_state(s):
    if s.kind!='receipt':return
    if s.allocated_amount<=EPS:s.state='unclaimed'
    elif s.allocated_amount>=s.amount-EPS:s.state='reconciled'
    else:s.state='partial'
def register_statement(db,b,u):
    if db.scalar(select(BankStatement).where(BankStatement.ref==b.ref)):raise HTTPException(409,'流水号已登记，请勿重复入账')
    s=BankStatement(**b.model_dump(),created_by=u.email)
    db.add(s);audit(db,u,f'登记银行流水 {b.ref} 金额{b.amount}');db.commit();return s
def create_batch(db,b,u):
    existing=db.scalar(select(ReconBatch).where(ReconBatch.client_key==b.client_key))
    if existing:return existing
    batch=ReconBatch(client_key=b.client_key,note=b.note.strip(),source='manual',created_by=u.email)
    db.add(batch);db.flush()
    for item in b.allocations:
        s=require(db,BankStatement,item.statement_id)
        if s.kind!='receipt':raise HTTPException(409,f'流水{s.ref}为冲正流水，不能再分配')
        if s.state=='reconciled':raise HTTPException(409,f'流水{s.ref}已核销完毕')
        c=require(db,WashSettlement,item.settlement_id)
        if c.state!='signed':raise HTTPException(409,f'合同CONTRACT-{c.id}未签结，不能核销')
        db.add(ReconAllocation(batch_id=batch.id,statement_id=s.id,settlement_id=c.id,amount=item.amount,source='manual',basis={'note':item.note.strip(),'by':u.email}))
    audit(db,u,f'登记核销批次{batch.id} 共{len(b.allocations)}笔分配');db.commit();return batch
def confirm_batch(db,key,u):
    batch=require(db,ReconBatch,key,True)
    if batch.state!='open':raise HTTPException(409,'批次已确认或作废，请勿重复办理')
    allocs=db.scalars(select(ReconAllocation).where(ReconAllocation.batch_id==batch.id,ReconAllocation.state=='pending').with_for_update()).all()
    if not allocs:raise HTTPException(409,'批次无待确认分配')
    per_statement={};per_settlement={}
    for a in allocs:
        per_statement[a.statement_id]=round(per_statement.get(a.statement_id,0)+a.amount,2)
        per_settlement[a.settlement_id]=round(per_settlement.get(a.settlement_id,0)+a.amount,2)
    # 先流水后合同、各自按id加锁，与冲正/其他批次保持同一锁序；行锁内读到的余款才是已提交口径
    statements={sid:require(db,BankStatement,sid,True) for sid in sorted(per_statement)}
    settlements={cid:require(db,WashSettlement,cid,True) for cid in sorted(per_settlement)}
    problems=[]
    for sid,need in per_statement.items():
        s=statements[sid]
        if s.kind!='receipt':problems.append(f'流水{s.ref}为冲正流水')
        elif s.allocated_amount+need>s.amount+EPS:problems.append(f'流水{s.ref}余款{s.amount-s.allocated_amount:.2f}不足本批{need:.2f}')
    for cid,need in per_settlement.items():
        c=settlements[cid]
        if c.state!='signed':problems.append(f'合同CONTRACT-{cid}未签结')
        elif received_sum(db,cid)+need>c.revenue+EPS:problems.append(f'合同CONTRACT-{cid}欠款{c.revenue-received_sum(db,cid):.2f}不足本批{need:.2f}')
    if problems:raise HTTPException(409,'整批拒绝：'+'；'.join(problems[:4]))
    now=datetime.utcnow()
    for a in allocs:a.state='confirmed';a.confirmed_by=u.email;a.confirmed_at=now
    for sid,need in per_statement.items():
        s=statements[sid];s.allocated_amount=round(s.allocated_amount+need,2);refresh_state(s)
    batch.state='confirmed';batch.confirmed_by=u.email;batch.confirmed_at=now
    audit(db,u,f'确认核销批次{key} 共{len(allocs)}笔');db.commit();return batch
def discard_batch(db,key,u):
    batch=require(db,ReconBatch,key,True)
    if batch.state!='open':raise HTTPException(409,'仅待确认批次可作废')
    for a in db.scalars(select(ReconAllocation).where(ReconAllocation.batch_id==batch.id,ReconAllocation.state=='pending')).all():a.state='discarded'
    batch.state='discarded';audit(db,u,f'作废核销批次{key}');db.commit();return batch
def reverse_allocation(db,key,u):
    a=require(db,ReconAllocation,key,True)
    if a.state=='reversed':raise HTTPException(409,'该笔核销已冲正，反向流水已存在')
    if a.state!='confirmed':raise HTTPException(409,'仅已核销分配可冲正，待确认分配请作废批次')
    if db.scalar(select(BankStatement).where(BankStatement.reverses_allocation_id==a.id)):raise HTTPException(409,'该笔核销已冲正，反向流水已存在')
    s=require(db,BankStatement,a.statement_id,True)
    c=require(db,WashSettlement,a.settlement_id)
    now=datetime.utcnow()
    a.state='reversed';a.reversed_by=u.email;a.reversed_at=now
    s.allocated_amount=round(s.allocated_amount-a.amount,2);refresh_state(s)
    rv=BankStatement(ref=f'RV-{s.ref}-{a.id}'[:60],received_at=now.date(),amount=-a.amount,payer=s.payer,memo=f'冲正 {s.ref} / CONTRACT-{c.id}，恢复双方余额',kind='reversal',state='reversal',reversal_of_id=s.id,reverses_allocation_id=a.id,created_by=u.email)
    db.add(rv);audit(db,u,f'冲正核销{a.id} 追加反向流水{rv.ref} 金额{rv.amount}');db.commit();return rv
def matcher_status(db):
    allocations=db.scalars(select(ReconAllocation)).all()
    model,evidence=match_model.train(allocations,db.scalars(select(BankStatement)).all(),db.scalars(select(WashSettlement)).all())
    return evidence
def suggest(db,u):
    allocations=db.scalars(select(ReconAllocation)).all()
    statements=db.scalars(select(BankStatement)).all();settlements=db.scalars(select(WashSettlement)).all()
    model,evidence=match_model.train(allocations,statements,settlements)
    if evidence['status']!='trained':return {'status':'insufficient','detail':'人工确认样本不足，请走人工核销','evidence':evidence,'batch_id':None,'suggestions':[],'manual':[]}
    received={c.id:received_sum(db,c.id) for c in settlements}
    pending_s={};pending_c={}
    for a in allocations:
        if a.state=='pending':
            pending_s[a.statement_id]=round(pending_s.get(a.statement_id,0)+a.amount,2)
            pending_c[a.settlement_id]=round(pending_c.get(a.settlement_id,0)+a.amount,2)
    open_c={c.id:round(c.revenue-received[c.id]-pending_c.get(c.id,0),2) for c in settlements if c.state=='signed'}
    open_c={k:v for k,v in open_c.items() if v>EPS}
    targets=[s for s in statements if s.kind=='receipt' and s.state in ['unclaimed','partial'] and s.id not in pending_s]
    batch=None;suggestions=[];manual=[]
    for s in sorted(targets,key=lambda x:x.id):
        remaining=round(s.amount-s.allocated_amount,2)
        if remaining<=EPS:continue
        scored=sorted(((match_model.score(model,s,remaining,c,open_c[c.id]),c) for c in settlements if c.id in open_c),key=lambda t:-t[0])
        if scored and scored[0][0]>=match_model.CONFIDENCE:
            prob,c=scored[0];amount=round(min(remaining,open_c[c.id]),2)
            if not batch:
                batch=ReconBatch(client_key='AUTO-'+uuid.uuid4().hex[:16],source='auto',note='匹配器自动建议',created_by=u.email);db.add(batch);db.flush()
            basis={'score':round(prob,4),'threshold':match_model.CONFIDENCE,'features':dict(zip(match_model.FEATURES,match_model.pair_features(remaining,open_c[c.id],s,c))),'model':{k:evidence[k] for k in ['confirmed_pairs','holdout_pairs','holdout_mismatch_rate']}}
            db.add(ReconAllocation(batch_id=batch.id,statement_id=s.id,settlement_id=c.id,amount=amount,source='auto',basis=basis))
            open_c[c.id]=round(open_c[c.id]-amount,2)
            if open_c[c.id]<=EPS:del open_c[c.id]
            suggestions.append({'statement':s.ref,'settlement_id':c.id,'amount':amount,'score':round(prob,4)})
        else:
            manual.append({'statement':s.ref,'remaining':remaining,'best_score':round(scored[0][0],4) if scored else None})
    if batch:
        audit(db,u,f'匹配器建议批次{batch.id} 共{len(suggestions)}笔');db.commit()
    return {'status':'ok','batch_id':batch.id if batch else None,'suggestions':suggestions,'manual':manual,'evidence':evidence}
