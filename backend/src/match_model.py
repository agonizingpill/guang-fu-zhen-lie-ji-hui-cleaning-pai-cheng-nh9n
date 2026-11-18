import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupShuffleSplit
FEATURES=['amount_exact','amount_cover','amount_ratio','ref_hit','days_since_sign']
MIN_PAIRS=6
MIN_GROUPS=4
CONFIDENCE=0.6
def refs_for(settlement):
    snap=settlement.snapshot or {}
    refs=[f'contract-{settlement.id}',f'wash-{settlement.mission_id}']
    for key in ['block_code','manifest']:
        if snap.get(key):refs.append(str(snap[key]).lower())
    return refs
def pair_features(remaining,outstanding,statement,settlement):
    text=((statement.payer or '')+' '+(statement.memo or '')).lower()
    top=max(remaining,outstanding)
    days=365.0
    if statement.received_at and settlement.signed_at:
        days=float(min(365,max(0,(statement.received_at-settlement.signed_at.date()).days)))
    return [1.0 if abs(remaining-outstanding)<0.01 else 0.0,1.0 if remaining>=outstanding-0.01 else 0.0,round(min(remaining,outstanding)/top,6) if top>0 else 0.0,1.0 if any(r in text for r in refs_for(settlement)) else 0.0,days]
def build_pairs(allocations,statements,settlements):
    # 按确认时间重放历史，还原每笔配对当时的流水余款与合同欠款，不用当前余额冒充历史特征
    stmts={s.id:s for s in statements};cands={c.id:c for c in settlements if c.state=='signed'}
    received={c.id:0.0 for c in settlements};used={s.id:0.0 for s in statements}
    rows=[];labels=[];groups=[]
    ordered=sorted(allocations,key=lambda a:(a.confirmed_at or a.created_at,a.id))
    for a in ordered:
        s=stmts.get(a.statement_id);c=cands.get(a.settlement_id)
        if not s or not c or s.kind!='receipt':continue
        remaining=round(s.amount-used[s.id],2);outstanding=round(c.revenue-received[c.id],2)
        rows.append(pair_features(remaining,outstanding,s,c));labels.append(1);groups.append(s.id)
        negatives=[o for oid,o in sorted(cands.items()) if oid!=c.id and round(o.revenue-received[oid],2)>0.004][:5]
        for o in negatives:
            rows.append(pair_features(remaining,round(o.revenue-received[o.id],2),s,o));labels.append(0);groups.append(s.id)
        received[c.id]=round(received[c.id]+a.amount,2);used[s.id]=round(used[s.id]+a.amount,2)
    return rows,labels,groups
_cache={}
def train(allocations,statements,settlements):
    confirmed=[a for a in allocations if a.state=='confirmed']
    fp=(len(confirmed),max([a.id for a in confirmed],default=0),max([str(a.confirmed_at) for a in confirmed],default=''))
    if _cache.get('fp')==fp:return _cache['model'],_cache['evidence']
    rows,labels,groups=build_pairs(confirmed,statements,settlements)
    positives=sum(labels);evidence={'status':'insufficient','min_pairs':MIN_PAIRS,'min_groups':MIN_GROUPS,'confirmed_pairs':positives,'features':FEATURES,'confidence_threshold':CONFIDENCE,'random_state':42,'method':'RandomForestClassifier / 100 trees / max_depth 8 / class_weight balanced'}
    model=None
    if positives>=MIN_PAIRS and len(set(groups))>=MIN_GROUPS:
        x=np.array(rows);y=np.array(labels);g=np.array(groups)
        model=RandomForestClassifier(n_estimators=100,max_depth=8,min_samples_leaf=2,random_state=42,n_jobs=1,class_weight='balanced')
        train_idx,test_idx=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(x,y,g))
        model.fit(x[train_idx],y[train_idx])
        def mismatch(idxs):
            wrong=total=0
            for i in idxs:
                if y[i]!=1:continue
                total+=1
                pool=[j for j in range(len(rows)) if groups[j]==groups[i]]
                best=max(pool,key=lambda j:model.predict_proba(x[j:j+1])[0][1])
                if best!=i:wrong+=1
            return wrong,total
        # 留出按流水分组：同一条流水的全部候选只落在训练或评估一侧，评估误配率才是未见流水的泛化指标
        train_wrong,train_total=mismatch(set(train_idx));test_wrong,test_total=mismatch(set(test_idx))
        evidence.update({'status':'trained','trained_pairs':int(y[train_idx].sum()),'holdout_pairs':test_total,'holdout_statements':len(set(groups[i] for i in test_idx)),'train_mismatch_rate':round(train_wrong/train_total,4) if train_total else None,'holdout_mismatch_rate':round(test_wrong/test_total,4) if test_total else None,'feature_importance':dict(zip(FEATURES,[round(v,4) for v in model.feature_importances_.tolist()]))})
        model.fit(x,y)
    _cache.clear();_cache.update({'fp':fp,'model':model,'evidence':evidence})
    return model,evidence
def score(model,statement,remaining,settlement,outstanding):
    return float(model.predict_proba(np.array([pair_features(remaining,outstanding,statement,settlement)]))[0][1])
