from datetime import datetime,timedelta
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,ArrayBlock,SoilingSurvey,WashMission
from src.revisit_models import WaterDelivery,FollowupSurvey
from src.auth import hash_password
from src.operations_models import WashCrew,WastewaterRecord,WashSettlement
from src.recon_models import BankStatement,ReconBatch,ReconAllocation

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','planner','viewer']:
            email=role+'@qingling.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Solar2026!'),role=role))
        for code,minutes in [('CREW-SOUTH',480),('CREW-RIDGE',360)]:
            if not db.scalar(select(WashCrew).where(WashCrew.code==code)):db.add(WashCrew(code=code,max_daily_minutes=minutes))
        blocks=[('SL-A01','南坡一号','南坡',150,23,780,1500),('SL-A02','南坡二号','南坡',120,25,630,1200),('SL-B01','脊线一号','脊线',100,18,520,900),('SL-C01','西坡一号','西坡',80,30,420,600)]
        for code,name,sector,cap,slope,area,water in blocks:
            if not db.scalar(select(ArrayBlock).where(ArrayBlock.code==code)):db.add(ArrayBlock(code=code,name=name,sector=sector,capacity_kw=cap,slope=slope,area_m2=area,water_liters=water))
        db.flush();rows=db.scalars(select(ArrayBlock).order_by(ArrayBlock.id)).all()
        measurements=[('SV-1117-A01',rows[0],800,35,18,3.2,88),('SV-1117-A02',rows[1],820,33,12,2.1,76),('SV-CLOUD-01',rows[2],240,23,8,1.2,18)]
        for code,block,irr,temp,rain,dust,power in measurements:
            if not db.scalar(select(SoilingSurvey).where(SoilingSurvey.code==code)):db.add(SoilingSurvey(code=code,block_id=block.id,capacity_kw=block.capacity_kw,slope=block.slope,irradiance=irr,module_temp=temp,rain_days=rain,dust=dust,observed_kw=power,state='recorded'))
        db.flush()
        block=db.scalar(select(ArrayBlock).where(ArrayBlock.code=='SL-C01'))
        if not db.scalar(select(WaterDelivery).where(WaterDelivery.delivery_code=='WD-DEMO-01')):
            db.add(WaterDelivery(block_id=block.id,delivery_code='WD-DEMO-01',liters=500,source='西坡蓄水池 / 水车02'))
        historical=db.scalar(select(SoilingSurvey).where(SoilingSurvey.code=='SV-DEMO-CLEAN'))
        if not historical:
            historical=SoilingSurvey(code='SV-DEMO-CLEAN',block_id=block.id,capacity_kw=block.capacity_kw,slope=block.slope,irradiance=800,module_temp=35,rain_days=15,dust=2,observed_kw=50,clean_kw=62,predicted_loss=12,recommended_water=100,state='closed')
            db.add(historical);db.flush()
        mission=db.scalar(select(WashMission).where(WashMission.survey_id==historical.id))
        if not mission:
            mission=WashMission(survey_id=historical.id,water_liters=100,available_liters=700,status='accepted',post_kw=62,post_irradiance=800,normalized_kw=62,verified_gain=12,dispatched_at=datetime.utcnow()-timedelta(days=7),accepted_at=datetime.utcnow()-timedelta(days=7))
            db.add(mission);db.flush()
        if not db.scalar(select(FollowupSurvey).where(FollowupSurvey.mission_id==mission.id,FollowupSurvey.days_after==2)):
            db.add(FollowupSurvey(mission_id=mission.id,days_after=2,irradiance=800,observed_kw=61,normalized_kw=61,normalized_loss=100/62,state='stable',baseline_snapshot={'post_kw':62,'post_irradiance':800,'accepted_at':mission.accepted_at.isoformat(),'block_id':block.id,'block_code':block.code,'survey_id':historical.id,'survey_code':historical.code,'threshold_pct':5}))
        _seed_recon(db,rows)
        db.commit();print({key:db.scalar(select(func.count()).select_from(model)) for key,model in [('users',User),('blocks',ArrayBlock),('surveys',SoilingSurvey)]})
def _seed_recon(db,rows):
    now=datetime.utcnow()
    survey=db.scalar(select(SoilingSurvey).where(SoilingSurvey.code=='SV-DEMO-CLEAN'))
    base=db.scalar(select(WashMission).where(WashMission.survey_id==survey.id))
    block=db.scalar(select(ArrayBlock).where(ArrayBlock.code=='SL-C01'))
    # 8份历史签结合同（含废水交接快照），为匹配器提供人工确认训练样本
    contracts=[]
    for i,g in enumerate([8,10,12,14,9,11,13,9],1):
        code=f'SV-HIST-26{i:02d}';blk=rows[(i-1)%len(rows)]
        sv=db.scalar(select(SoilingSurvey).where(SoilingSurvey.code==code))
        if not sv:
            observed=round(blk.capacity_kw*0.6,1)
            sv=SoilingSurvey(code=code,block_id=blk.id,capacity_kw=blk.capacity_kw,slope=blk.slope,irradiance=800,module_temp=34,rain_days=10,dust=2.5,observed_kw=observed,clean_kw=observed+g,predicted_loss=g,recommended_water=100,state='closed')
            db.add(sv);db.flush()
        m=db.scalar(select(WashMission).where(WashMission.survey_id==sv.id))
        if not m:
            m=WashMission(survey_id=sv.id,water_liters=100,available_liters=500,status='accepted',post_kw=sv.observed_kw+g,post_irradiance=800,normalized_kw=sv.observed_kw+g,verified_gain=g,dispatched_at=now-timedelta(days=40-i),accepted_at=now-timedelta(days=40-i))
            db.add(m);db.flush()
        d=db.scalar(select(WastewaterRecord).where(WastewaterRecord.mission_id==m.id))
        if not d:
            d=WastewaterRecord(mission_id=m.id,used_liters=100,recovered_liters=80,recovery_pct=80,disposal_method='移动沉淀池过滤，回用于站区道路抑尘',manifest=f'WW-HIST-{i:02d}',state='handed_over',verified_by='admin@qingling.test',received_by='环保接收员 王工',receipt='沉淀池入场签收单，现场核对水量无误')
            db.add(d);db.flush()
        st=db.scalar(select(WashSettlement).where(WashSettlement.mission_id==m.id))
        if not st:
            revenue=round(g*80,2);cost=round(100*0.3,2)
            st=WashSettlement(mission_id=m.id,price_per_kw=80,cost_per_liter=0.3,revenue=revenue,water_cost=cost,margin=round(revenue-cost,2),snapshot={'mission_id':m.id,'block_code':blk.code,'survey_code':sv.code,'verified_gain_kw':g,'used_liters':100,'accepted_at':m.accepted_at.isoformat(),'wastewater_id':d.id,'manifest':d.manifest,'recovered_liters':80,'receipt':d.receipt},state='signed',signed_by='admin@qingling.test',signed_at=now-timedelta(days=38-i))
            db.add(st);db.flush()
        contracts.append(st)
    # 当前待回款合同：历史验收任务的结算凭据
    current=db.scalar(select(WashSettlement).where(WashSettlement.mission_id==base.id))
    if not current:
        d=db.scalar(select(WastewaterRecord).where(WastewaterRecord.mission_id==base.id))
        if not d:
            d=WastewaterRecord(mission_id=base.id,used_liters=100,recovered_liters=85,recovery_pct=85,disposal_method='移动沉淀池过滤，回用于站区道路抑尘',manifest='WW-DEMO-CLEAN',state='handed_over',verified_by='admin@qingling.test',received_by='环保接收员 王工',receipt='沉淀池入场签收单，现场核对水量无误')
            db.add(d);db.flush()
        revenue=round(12*80,2);cost=round(100*0.3,2)
        current=WashSettlement(mission_id=base.id,price_per_kw=80,cost_per_liter=0.3,revenue=revenue,water_cost=cost,margin=round(revenue-cost,2),snapshot={'mission_id':base.id,'block_code':block.code,'survey_code':survey.code,'verified_gain_kw':12,'used_liters':100,'accepted_at':base.accepted_at.isoformat(),'wastewater_id':d.id,'manifest':d.manifest,'recovered_liters':85,'receipt':d.receipt},state='signed',signed_by='admin@qingling.test',signed_at=now-timedelta(days=2))
        db.add(current);db.flush()
    def ensure_statement(ref,days,amount,payer,memo,**kw):
        s=db.scalar(select(BankStatement).where(BankStatement.ref==ref))
        if not s:
            s=BankStatement(ref=ref,received_at=(now-timedelta(days=days)).date(),amount=amount,payer=payer,memo=memo,created_by='planner@qingling.test',**kw)
            db.add(s);db.flush()
        return s
    c=contracts
    if not db.scalar(select(ReconBatch).where(ReconBatch.client_key=='SEED-HIST-01')):
        hist=ReconBatch(client_key='SEED-HIST-01',source='manual',note='历史人工核销（匹配器训练样本）',state='confirmed',created_by='planner@qingling.test',confirmed_by='admin@qingling.test',confirmed_at=now-timedelta(days=17))
        db.add(hist);db.flush()
        def alloc(s,st,amount,days,**kw):
            kw.setdefault('state','confirmed')
            a=ReconAllocation(batch_id=hist.id,statement_id=s.id,settlement_id=st.id,amount=amount,source='manual',basis={'note':'人工核对合同号与金额','by':'planner@qingling.test'},confirmed_by='admin@qingling.test',confirmed_at=now-timedelta(days=days),**kw)
            db.add(a);db.flush();return a
        s1=ensure_statement('ST-2609-01',33,c[0].revenue,'晴岭电站财务部',f'CONTRACT-{c[0].id} 清洗服务费',state='reconciled',allocated_amount=c[0].revenue)
        alloc(s1,c[0],c[0].revenue,32)
        s2=ensure_statement('ST-2609-02',31,1100,'晴岭电站财务部',f'CONTRACT-{c[1].id} 清洗服务费',state='partial',allocated_amount=c[1].revenue)
        alloc(s2,c[1],c[1].revenue,30)
        err=alloc(s2,c[2],300,30,state='reversed',reversed_by='admin@qingling.test',reversed_at=now-timedelta(days=29))
        db.add(BankStatement(ref=f'RV-ST-2609-02-{err.id}',received_at=(now-timedelta(days=29)).date(),amount=-300,payer=s2.payer,memo=f'冲正 ST-2609-02 / CONTRACT-{c[2].id}，恢复双方余额',kind='reversal',state='reversal',reversal_of_id=s2.id,reverses_allocation_id=err.id,created_by='admin@qingling.test'))
        s3=ensure_statement('ST-2609-03',29,c[2].revenue,'晴岭电站财务部',f'CONTRACT-{c[2].id} 服务费',state='reconciled',allocated_amount=c[2].revenue)
        alloc(s3,c[2],c[2].revenue,28)
        s4=ensure_statement('ST-2609-04',27,c[3].revenue,'南坡新能源结算中心','节水清洗服务费结算',state='reconciled',allocated_amount=c[3].revenue)
        alloc(s4,c[3],c[3].revenue,26)
        s5=ensure_statement('ST-2609-05',25,c[4].revenue+c[5].revenue,'晴岭电站财务部',f'CONTRACT-{c[4].id} CONTRACT-{c[5].id} 合并汇款',state='reconciled',allocated_amount=c[4].revenue+c[5].revenue)
        alloc(s5,c[4],c[4].revenue,24);alloc(s5,c[5],c[5].revenue,24)
        s6=ensure_statement('ST-2609-06',23,624,'脊线运维合作方',f'CONTRACT-{c[6].id} 首期',state='reconciled',allocated_amount=624)
        alloc(s6,c[6],624,22)
        s8=ensure_statement('ST-2609-08',19,1000,'西坡光伏合作社',f'CONTRACT-{c[7].id} 部分回款',state='partial',allocated_amount=400)
        alloc(s8,c[7],400,18)
    if not db.scalar(select(ReconBatch).where(ReconBatch.client_key=='SEED-TODO-01')):
        s7=ensure_statement('ST-2609-07',21,416,'脊线运维合作方',f'CONTRACT-{c[6].id} 尾期')
        todo=ReconBatch(client_key='SEED-TODO-01',source='manual',note='尾期回款待主管确认',created_by='planner@qingling.test')
        db.add(todo);db.flush()
        db.add(ReconAllocation(batch_id=todo.id,statement_id=s7.id,settlement_id=c[6].id,amount=416,source='manual',basis={'note':'尾期416，与首期624合计1040','by':'planner@qingling.test'}))
    ensure_statement('ST-2026-NEW1',1,960,'晴岭电站财务部',f'CONTRACT-{current.id} 清洗服务费')
    ensure_statement('ST-2026-NEW2',0,5000,'岭北新能源有限公司','季度预付款')
if __name__=='__main__':seed()
