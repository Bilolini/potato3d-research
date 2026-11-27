"""Train and score the frozen, matched center/RAFT point-cloud comparison."""

import argparse
from contextlib import contextmanager
import csv
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

import inputs as data

SEEDS = (133,527,2401)
BATCH = 16
EPOCHS = 100
SMOKE_STEPS = 250
MC_SEED = 5272401
DRAWS = 10_000


def layers(widths):
    blocks = []
    for a,b in zip(widths[:-1],widths[1:],strict=True):
        blocks.extend((nn.Linear(a,b),nn.LayerNorm(b),nn.SiLU()))
    return nn.Sequential(*blocks)


def gather(features, indices):
    batch = torch.arange(len(features)).reshape(-1,*([1]*(indices.ndim-1)))
    return features[batch,indices]


class CompactPointRAFT(nn.Module):
    """CPU set abstraction and object-height embedding, fitted from random initialization."""

    def __init__(self):
        super().__init__()
        self.local1=layers((3,32,32,64))
        self.local2=layers((67,64,64,96))
        self.global_encoder=layers((99,96,128))
        self.height=layers((1,8,8))
        self.regression=nn.Sequential(nn.Linear(136,64),nn.LayerNorm(64),nn.SiLU(),nn.Dropout(.15),
                                      nn.Linear(64,32),nn.LayerNorm(32),nn.SiLU(),nn.Dropout(.15),nn.Linear(32,1))

    def forward(self, x):
        points=x["xyz"]
        pos1=gather(points,x["anchors1"])
        relative1=gather(points,x["knn1"])-pos1[:,:,None,:]
        feat1=self.local1(relative1).amax(dim=2)
        pos2=gather(pos1,x["anchors2"])
        relative2=gather(pos1,x["knn2"])-pos2[:,:,None,:]
        feat2=self.local2(torch.cat((relative2,gather(feat1,x["knn2"])),dim=-1)).amax(dim=2)
        global_feat=self.global_encoder(torch.cat((pos2,feat2),dim=-1)).amax(dim=1)
        height=self.height(x["height"][:,None])
        return self.regression(torch.cat((global_feat,height),dim=-1))[:,0]


def path(name):
    return data.STUDY/name


def sha(p):
    return data.pilot.digest(p)


def read(p):
    return data.pilot.read_json(p)


def save(p,value):
    data.pilot.freeze_check(p,value)


def verified_inputs():
    frozen = data.load_freeze()
    meta = read(path("inputs_manifest.json"))
    store=data.OUTPUT/"point_inputs.npz"
    if meta["frame_manifest_sha256"]!=sha(path("frame_manifest.json")) or meta["dataset_sha256"]!=sha(store):
        raise ValueError("Point features differ from their frozen roster or hash")
    if any("/2_sfm/" in filename or filename.endswith("tmatrix.zip") for filename in meta["raw_payload_archives"]):
        raise ValueError("An input opened a forbidden reference archive")
    rows=meta["entries"]
    if [(r["tuber"],r["split"]) for r in rows]!=[(r["tuber"],r["split"]) for r in frozen["roster"]]:
        raise ValueError("Input features differ from the frozen cohort")
    by_id={r["tuber"]:r for r in rows}
    available=[r for r in rows if r["input_index"] is not None]
    if [r["input_index"] for r in available]!=list(range(len(available))):
        raise ValueError("Unexpected feature index mapping")
    with np.load(store,allow_pickle=False) as source:
        arrays={k:torch.from_numpy(source[k]) for k in source.files}
    clouds={arm:{part:arrays[f"{arm}_{part}"] for part in ("xyz","height","anchors1","anchors2","knn1","knn2")}
            for arm in data.ARMS}
    for item in clouds.values():
        if tuple(item["xyz"].shape)!=(len(available),data.SAMPLE_COUNT,3) or not torch.isfinite(item["xyz"]).all():
            raise ValueError("Invalid matched sample size or nonfinite XYZ")
    return frozen,meta,by_id,clouds


def freeze_analysis():
    verified_inputs()
    seal={
        "protocol_sha256":sha(path("protocol.md")),"inputs_sha256":sha(path("inputs_manifest.json")),
        "code_sha256":sha(Path(__file__)),"torch":torch.__version__,"seeds":list(SEEDS),"epochs":EPOCHS,
        "parameters":sum(p.numel() for p in CompactPointRAFT().parameters()),
    }
    save(path("analysis_freeze.json"),seal)
    print("Analysis, architecture, split and seed budget frozen.",flush=True)


def verify_seal():
    seal=read(path("analysis_freeze.json"))
    if any(seal[k]!=v for k,v in {"protocol_sha256":sha(path("protocol.md")),
                                 "inputs_sha256":sha(path("inputs_manifest.json")),
                                 "code_sha256":sha(Path(__file__)),"torch":torch.__version__}.items()):
        raise ValueError("Frozen comparison changed")


def weights(ids):
    keep=set(ids)
    mapped={}
    with data.TRAITS.open(newline="") as file:
        for row in csv.DictReader(file):
            key=row["label"]
            if key not in keep:
                continue
            if key in mapped:
                raise ValueError(f"Duplicate measured weight for {key}")
            try:
                grams=float(row["weight_g_inctack"])
            except (TypeError,ValueError):
                grams=float("nan")
            mapped[key]=grams if math.isfinite(grams) and grams>0 else None
    return {t:mapped.get(t) for t in keep}


def control():
    verify_seal()
    _,meta,_,_=verified_inputs()
    started=time.perf_counter()
    training=[r for r in meta["entries"] if r["split"]=="train" and r["error"] is None]
    truth=weights(r["tuber"] for r in training)
    usable=[r for r in training if truth[r["tuber"]] is not None]
    output={"analysis_sha256":sha(path("analysis_freeze.json")),"training_ids":[r["tuber"] for r in usable],
            "models":{},"predictions":{}}
    for arm in data.ARMS:
        x=np.asarray([r["arms"][arm]["proxy_cm3"] for r in usable])
        y=np.asarray([truth[r["tuber"]] for r in usable])
        coeff,_,rank,_=np.linalg.lstsq(np.column_stack((np.ones(len(x)),x)),y,rcond=None)
        if rank!=2:
            raise ValueError("Matched control is rank deficient")
        output["models"][arm]={"intercept_g":float(coeff[0]),"g_per_cm3":float(coeff[1])}
        output["predictions"][arm]={
            r["tuber"]: None if r["error"] else max(0.,float(coeff[0]+coeff[1]*r["arms"][arm]["proxy_cm3"]))
            for r in meta["entries"] if r["split"]=="val"
        }
    output["wall_s"]=time.perf_counter()-started
    data.pilot.write_json(path("control_fit.json"),output)
    print("Matched area-height regressions and evaluation predictions saved without joining evaluation weights.",flush=True)


def batch(cloud, idx):
    return {name: tensor[idx] for name,tensor in cloud.items()}


def normalized_truth(ids, by_id, truth):
    idx=torch.tensor([by_id[t]["input_index"] for t in ids],dtype=torch.long)
    labels=torch.tensor([truth[t] for t in ids],dtype=torch.float32)
    return idx,labels


@torch.no_grad()
def inference(net,cloud,idx,mu,sd):
    net.eval()
    return torch.cat([torch.clamp(net(batch(cloud,i))*sd+mu,min=0.) for i in idx.split(BATCH)])


def fit_network(cloud, ids, by_id, truth, seed, num_epochs, inner_ids=None, smoke=False):
    torch.manual_seed(seed)
    shuffle=torch.Generator().manual_seed(seed)
    net=CompactPointRAFT()
    opt=torch.optim.Adam(net.parameters(),lr=.001,weight_decay=.0001)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=EPOCHS,eta_min=.0001)
    idx,y=normalized_truth(ids,by_id,truth)
    mu,sd=y.mean().item(),y.std(unbiased=False).item()
    if not sd>0:
        raise ValueError("Training target variation is zero")
    y_scaled=(y-mu)/sd
    loss_fn=nn.SmoothL1Loss(beta=20./sd)
    losses=[]
    if inner_ids is not None:
        inner_idx,inner_y=normalized_truth(inner_ids,by_id,truth)
    before=float(torch.mean(torch.abs(inference(net,cloud,idx,mu,sd)-y))) if smoke else None
    started=time.perf_counter()
    for _ in range(num_epochs):
        net.train()
        ordering=torch.randperm(len(idx),generator=shuffle)
        for positions in ordering.split(BATCH):
            opt.zero_grad(set_to_none=True)
            estimates=net(batch(cloud,idx[positions]))
            loss=loss_fn(estimates,y_scaled[positions])
            if not torch.isfinite(loss):
                raise ValueError(f"Nonfinite training loss at seed {seed}")
            loss.backward()
            opt.step()
        if not smoke:
            scheduler.step()
        if inner_ids is not None:
            val=inference(net,cloud,inner_idx,mu,sd)
            losses.append(float(torch.mean(torch.abs(val-inner_y))))
    elapsed=time.perf_counter()-started
    after=float(torch.mean(torch.abs(inference(net,cloud,idx,mu,sd)-y))) if smoke else None
    return net,{"mean_g":mu,"sd_g":sd,"inner_mae_g":losses,"wall_s":elapsed,
                "smoke_mae_initial_g":before,"smoke_mae_final_g":after}


def valid_ids(ids,by_id,truth):
    return [t for t in ids if by_id[t]["error"] is None and truth[t] is not None]


def smoke():
    verify_seal()
    if not path("control_fit.json").is_file():
        raise ValueError("Run the matched simple control first")
    frozen,_,by_id,clouds=verified_inputs()
    ids=frozen["smoke_ids"]
    truth=weights(ids)
    if ids!=valid_ids(ids,by_id,truth):
        raise ValueError("A frozen smoke-fit potato does not have paired inputs and a weight")
    records={}
    for arm in data.ARMS:
        _,summary=fit_network(clouds[arm],ids,by_id,truth,133,SMOKE_STEPS,smoke=True)
        records[arm]=summary
    passed=all(info["smoke_mae_final_g"] <= .5*info["smoke_mae_initial_g"] for info in records.values())
    data.pilot.write_json(path("smoke_fit.json"),{"ids":ids,"arms":records,"passed":passed,"seed":133,
                                              "analysis_sha256":sha(path("analysis_freeze.json"))})
    if not passed:
        raise ValueError("Small training-only fit did not meet the frozen threshold")
    print("Training-only smoke passed:",{m:(round(r["smoke_mae_initial_g"],1),round(r["smoke_mae_final_g"],1))
                                        for m,r in records.items()},flush=True)


def train():
    verify_seal()
    smoke_result=read(path("smoke_fit.json"))
    if not smoke_result["passed"] or smoke_result["analysis_sha256"]!=sha(path("analysis_freeze.json")):
        raise ValueError("Current frozen architecture must pass its training-only smoke test")
    control_fit=read(path("control_fit.json"))
    if control_fit["analysis_sha256"]!=sha(path("analysis_freeze.json")):
        raise ValueError("Matched control differs from the frozen analysis")
    frozen,meta,by_id,clouds=verified_inputs()
    all_train=[r["tuber"] for r in meta["entries"] if r["split"]=="train"]
    truth=weights(all_train)
    train_ids=valid_ids(all_train,by_id,truth)
    internal=valid_ids(frozen["inner_fit"],by_id,truth)
    validation=valid_ids(frozen["inner_validation"],by_id,truth)
    if len(internal)<2 or len(validation)<2 or train_ids!=control_fit["training_ids"]:
        raise ValueError("Incomplete or mismatched training and selection pools")
    fitted_dir=path("fits")
    fitted_dir.mkdir(exist_ok=True)
    records=[]
    for seed in SEEDS:
        seed_path=fitted_dir/f"seed_{seed}.json"
        if seed_path.exists():
            record=read(seed_path)
            if record["analysis_sha256"]!=sha(path("analysis_freeze.json")) or record["seed"]!=seed:
                raise ValueError("An existing seed record differs from the frozen comparison")
            records.append(record)
            continue
        select={}
        for arm in data.ARMS:
            _,select[arm]=fit_network(clouds[arm],internal,by_id,truth,seed,EPOCHS,validation)
            print(f"Seed {seed} {arm} inner fit complete",flush=True)
        scores=np.mean([select[m]["inner_mae_g"] for m in data.ARMS],axis=0)
        if not np.isfinite(scores).all():
            raise ValueError("Nonfinite inner model-selection metrics")
        epoch=int(scores.argmin())+1
        fits={}
        for arm in data.ARMS:
            net,result=fit_network(clouds[arm],train_ids,by_id,truth,seed,epoch)
            filename=f"{arm}_{seed}.pt"
            ckpt=fitted_dir/filename
            torch.save(net.state_dict(),ckpt)
            fits[arm]={"checkpoint":filename,"sha256":sha(ckpt),**result}
            print(f"Seed {seed} {arm} refit complete at shared epoch {epoch}",flush=True)
        record={"seed":seed,"shared_epoch":epoch,"selection":select,"fits":fits,
                "analysis_sha256":sha(path("analysis_freeze.json"))}
        save(seed_path,record)
        records.append(record)
    data.pilot.write_json(path("train_fit.json"),{
        "training_ids":train_ids,"inner_fit":internal,"inner_validation":validation,
        "analysis_sha256":sha(path("analysis_freeze.json")),"model_selection":"earliest joint inner-validation MAE minimum per seed",
        "records":records,
    })


def predict():
    verify_seal()
    fit=read(path("train_fit.json"))
    if fit["analysis_sha256"]!=sha(path("analysis_freeze.json")) or [x["seed"] for x in fit["records"]]!=list(SEEDS):
        raise ValueError("Frozen fit or paired seed roster changed")
    _,meta,by_id,clouds=verified_inputs()
    evaluation=[r["tuber"] for r in meta["entries"] if r["split"]=="val"]
    valid=[t for t in evaluation if by_id[t]["error"] is None]
    idx=torch.tensor([by_id[t]["input_index"] for t in valid],dtype=torch.long)
    predictions,seconds={},{}
    for experiment in fit["records"]:
        seed=str(experiment["seed"])
        predictions[seed],seconds[seed]={},{}
        for arm in data.ARMS:
            recipe=experiment["fits"][arm]
            ckpt=path("fits")/recipe["checkpoint"]
            if sha(ckpt)!=recipe["sha256"]:
                raise ValueError("Frozen fitted checkpoint changed")
            net=CompactPointRAFT()
            net.load_state_dict(torch.load(ckpt,map_location="cpu",weights_only=True))
            started=time.perf_counter()
            result=inference(net,clouds[arm],idx,recipe["mean_g"],recipe["sd_g"]).tolist() if len(idx) else []
            if not np.isfinite(result).all():
                raise ValueError(f"Nonfinite evaluation prediction at seed {seed}, {arm}")
            seconds[seed][arm]=time.perf_counter()-started
            recorded=dict(zip(valid,result,strict=True))
            predictions[seed][arm]={t:recorded.get(t) for t in evaluation}
    data.pilot.write_json(path("predictions_before_targets.json"),{
        "fit_sha256":sha(path("train_fit.json")),"control_sha256":sha(path("control_fit.json")),
        "evaluation_ids":evaluation,"learned_predictions_g":predictions,"inference_wall_s":seconds,
    })
    print("All evaluation predictions frozen before opening evaluation weights.",flush=True)


def paired(rows, method):
    a,b=[np.asarray([r[f"{method}_{arm}_abs_error_g"] for r in rows],dtype=float) for arm in data.ARMS]
    delta=b-a
    rng=np.random.default_rng(MC_SEED)
    indices=rng.integers(len(rows),size=(DRAWS,len(rows)))
    interval=np.quantile(delta[indices].mean(axis=1),[.025,.975])
    return {"n":len(rows),"center_mae_g":float(a.mean()),"fused_mae_g":float(b.mean()),
            "mean_change_g":float(delta.mean()),"bootstrap_95_g":interval.tolist(),
            "wins":int((delta < -1e-9).sum()),"ties":int((abs(delta)<=1e-9).sum()),
            "losses":int((delta>1e-9).sum())}


def score():
    verify_seal()
    if path("results.json").exists():
        raise ValueError("The frozen evaluation already has a result")
    predictions=read(path("predictions_before_targets.json"))
    if (predictions["fit_sha256"]!=sha(path("train_fit.json"))
            or predictions["control_sha256"]!=sha(path("control_fit.json"))):
        raise ValueError("Saved prediction and fit hashes changed")
    frozen,meta,by_id,_=verified_inputs()
    control_fit=read(path("control_fit.json"))
    network_fit=read(path("train_fit.json"))
    learned=predictions["learned_predictions_g"]
    ids=predictions["evaluation_ids"]
    if ids!=[q["tuber"] for q in frozen["roster"] if q["split"]=="val"]:
        raise ValueError("Evaluation prediction roster differs from the freeze")
    measured=weights(ids)
    rows=[]
    for t in ids:
        sample=by_id[t]
        row={"tuber":t,"weight_measured_g":measured[t],"failure":sample["error"] or "",
             "center_voxels":sample["arms"].get("center",{}).get("voxels"),
             "fused_voxels":sample["arms"].get("fused",{}).get("voxels")}
        if measured[t] is None:
            row["failure"]="Missing measured weight"
        for arm in data.ARMS:
            v=[learned[str(seed)][arm][t] for seed in SEEDS]
            means={"control":control_fit["predictions"][arm][t],
                   "learned":sum(v)/len(v) if all(x is not None for x in v) else None,
                   **{str(seed):elem for seed,elem in zip(SEEDS,v,strict=True)}}
            for method,p in means.items():
                row[f"{method}_{arm}_prediction_g"]=p
                row[f"{method}_{arm}_abs_error_g"]=abs(p-measured[t]) if p is not None and measured[t] is not None else None
        for method in ("control","learned",*map(str,SEEDS)):
            a,b=[row[f"{method}_{arm}_abs_error_g"] for arm in data.ARMS]
            row[f"{method}_fused_minus_center_g"]=b-a if a is not None and b is not None else None
        rows.append(row)
    matched=[r for r in rows if all(r[f"{method}_fused_minus_center_g"] is not None for method in ("control","learned",*map(str,SEEDS)))]
    if not matched:
        raise ValueError("No comparable evaluation potatoes")
    stats={m:paired(matched,m) for m in ("control","learned",*map(str,SEEDS))}
    spread={key:float(np.std([stats[str(seed)][key] for seed in SEEDS],ddof=1))
            for key in ("center_mae_g","fused_mae_g","mean_change_g")}
    report={"enrolled":len(rows),"pairs":len(matched),"failures":[r["tuber"] for r in rows if r not in matched],
            "training_n":len(network_fit["training_ids"]),"endpoints":stats,"seed_mae_sd_g":spread,
            "geometry_replay_wall_s":meta["elapsed_s"],"control_wall_s":control_fit["wall_s"],
            "learning_wall_s":{arm:sum(r["selection"][arm]["wall_s"]+r["fits"][arm]["wall_s"]
                                      for r in network_fit["records"]) for arm in data.ARMS},
            "prediction_wall_s":predictions["inference_wall_s"],
            "selected_epochs":{str(r["seed"]):r["shared_epoch"] for r in network_fit["records"]},
            "frozen_prediction_sha256":sha(path("predictions_before_targets.json"))}
    with path("per_potato.csv").open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    data.pilot.write_json(path("results.json"),report)
    print({key:stats[key] for key in ("learned","control")},flush=True)


if __name__=="__main__":
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("freeze","control","smoke","train","predict","score"))
    args=parser.parse_args()
    {"freeze":freeze_analysis,"control":control,"smoke":smoke,"train":train,"predict":predict,"score":score}[args.stage]()
