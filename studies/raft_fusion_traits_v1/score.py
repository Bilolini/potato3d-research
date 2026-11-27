"""Fit and evaluate the frozen development comparison without opening SfM assets."""

import argparse
import csv
from collections import Counter
import math
from pathlib import Path
import sys
import time

import numpy as np

import roster as prep

sys.path.insert(0, str(prep.ROOT))
from studies.multiframe_weight_v1 import run as baseline

METHODS = ("A","B","C","D")
TRAITS = ("weight","volume")
UNITS = {"weight":"g","volume":"mL"}
DRAWS = 10_000


def hash_at(name):
    return prep.pilot.digest(prep.STUDY/name)


def seal_analysis():
    prep.read_freeze()
    result = {"protocol_sha256":hash_at("protocol.md"),"frame_manifest_sha256":hash_at("frame_manifest.json"),
              "analysis_code_sha256":hash_at("score.py"),"archived_comparison_code_sha256":prep.pilot.digest(baseline.HERE/"run.py")}
    prep.pilot.freeze_check(prep.STUDY/"analysis_freeze.json",result)
    print("Analysis frozen before fitting.",flush=True)
    return result


def verify_analysis():
    data = prep.pilot.read_json(prep.STUDY/"analysis_freeze.json")
    if (data["protocol_sha256"]!=hash_at("protocol.md") or data["frame_manifest_sha256"]!=hash_at("frame_manifest.json")
            or data["analysis_code_sha256"]!=hash_at("score.py")
            or data["archived_comparison_code_sha256"]!=prep.pilot.digest(baseline.HERE/"run.py")):
        raise ValueError("Frozen scoring specification changed")
    return data


def verified_features(freeze):
    output = prep.OUTPUTS
    run = prep.pilot.read_json(output/"feature_run.json")
    recipe = prep.pilot.read_json(output/"feature_recipe.json")
    if (recipe!=run["recipe"] or recipe["frame_manifest_sha256"]!=freeze["frame_manifest_sha256"]
            or run["fingerprint"]!=prep.pilot.digest(output/"feature_recipe.json")
            or recipe["code_sha256"]!=hash_at("features.py")
            or recipe["checkpoint_sha256"]!=prep.pilot.CHECKPOINT_HASH):
        raise ValueError("Feature provenance differs from the frozen analysis")
    roster = prep.read_freeze()["roster"]
    if [(p["tuber"],p["split"]) for p in roster] != [(p["tuber"],p["split"]) for p in run["records"]]:
        raise ValueError("Extracted rows do not cover the frozen roster in order")
    rows = []
    for recipe_row, frozen_row in zip(run["records"],roster,strict=True):
        path = output/"features"/recipe_row["cache_file"]
        if prep.pilot.digest(path)!=recipe_row["cache_sha256"]:
            raise ValueError(f"Saved feature hash changed: {path.name}")
        data = prep.pilot.read_json(path)
        if (data["feature_fingerprint"]!=run["fingerprint"] or data["tuber"]!=frozen_row["tuber"]
                or data["selected"]!=frozen_row["selected"] or data["split"]!=frozen_row["split"]):
            raise ValueError("Cached feature row differs from frozen ID or frame choices")
        rows.append(data)
    return run, rows


def reference(ids):
    ids = set(ids)
    values = {}
    with prep.TRAITS.open(newline="") as f:
        reader = csv.DictReader(f)
        if not {"label", *prep.ARCHIVE_TARGETS.values()} <= set(reader.fieldnames or ()):
            raise ValueError("The measured trait schema changed")
        for row in reader:
            tuber = row["label"]
            if tuber not in ids:
                continue
            if tuber in values:
                raise ValueError(f"Ambiguous measurement row {tuber}")
            entry = {}
            for trait, key in prep.ARCHIVE_TARGETS.items():
                try:
                    number = float(row[key])
                except (ValueError, TypeError):
                    number = float("nan")
                entry[trait] = number if math.isfinite(number) and number > 0. else None
            values[tuber] = entry
    return {t:values.get(t,dict.fromkeys(TRAITS)) for t in ids}


def single_frame_values(features, method):
    return features[method] if method=="B" else [features[method]]


def fit_model(rows, measured, trait, method):
    vectors, labels, weights = [], [], []
    for row in rows:
        v = single_frame_values(row["features"],method)
        vectors.extend(v)
        labels.extend([measured[row["tuber"]][trait]]*len(v))
        weights.extend([1./len(v)]*len(v))
    design = np.column_stack((np.ones(len(vectors)),vectors))
    scale = np.sqrt(weights)
    coefs,_,rank,_ = np.linalg.lstsq(design*scale[:,None], np.asarray(labels)*scale, rcond=None)
    if rank!=2 or not np.isfinite(coefs).all():
        raise ValueError(f"Invalid {method} {trait} training fit")
    return {"intercept":float(coefs[0]),"slope_per_cm3":float(coefs[1]),
            "rows":len(vectors),"potatoes":len(rows),"unit":UNITS[trait]}


def make_predictions(rows, models):
    predictions = []
    for row in rows:
        output = {"tuber":row["tuber"],"prediction":{},"B_individual_predictions":{}}
        for trait in TRAITS:
            output["prediction"][trait] = {}
            for method in METHODS:
                value = None
                if row["features"][method] is not None:
                    coefs = models[trait][method]
                    x = single_frame_values(row["features"],method)
                    guesses = np.maximum(0., coefs["intercept"]+coefs["slope_per_cm3"]*np.asarray(x))
                    value = float(np.mean(guesses))
                    if method=="B":
                        output["B_individual_predictions"][trait]=guesses.tolist()
                output["prediction"][trait][method] = value
        predictions.append(output)
    return predictions


def fit():
    freeze = verify_analysis()
    run,rows = verified_features(freeze)
    start = time.perf_counter()
    training = [row for row in rows if row["split"]=="train"]
    evaluation = [row for row in rows if row["split"]=="val"]
    measured = reference(row["tuber"] for row in training)
    models,pools,excluded = {},{},{}
    for trait in TRAITS:
        pool = []
        problems = {}
        for row in training:
            key = row["tuber"]
            reason = [f"missing {m} feature" for m in METHODS if row["features"][m] is None]
            if measured[key][trait] is None:
                reason.append(f"missing or invalid measured {trait}")
            if reason:
                problems[key] = reason
            else:
                pool.append(row)
        models[trait] = {m:fit_model(pool,measured,trait,m) for m in METHODS}
        pools[trait] = [row["tuber"] for row in pool]
        excluded[trait] = problems

    model_file = prep.STUDY/"train_fit.json"
    fit_elapsed = time.perf_counter()-start
    data = {"models":models,"training_ids":pools,"exclusions":excluded,"training_enrolled":len(training),
            "analysis_freeze_sha256":hash_at("analysis_freeze.json"),
            "feature_run_sha256":prep.pilot.digest(prep.OUTPUTS/"feature_run.json"),
            "fit_wall_s":fit_elapsed}
    if model_file.exists():
        old=prep.pilot.read_json(model_file)
        if {k:v for k,v in old.items() if k!="fit_wall_s"}!={k:v for k,v in data.items() if k!="fit_wall_s"}:
            raise ValueError("Train-only models or their freeze have changed")
    else:
        prep.pilot.write_json(model_file,data)
    predictions = make_predictions(evaluation,models)
    prep.pilot.freeze_check(prep.STUDY/"predictions_before_targets.json",{
        "train_fit_sha256":hash_at("train_fit.json"),"evaluation_enrolled":len(evaluation),
        "predictions":predictions,
    })
    print("Fitted and saved predictions without evaluation targets. Training complete:",
          {trait:len(pools[trait]) for trait in TRAITS},flush=True)


def mean_mae(rows,trait,methods):
    if not rows:
        return dict.fromkeys(methods)
    return {m:float(np.mean([r[f"{trait}_{m}_abs_error"] for r in rows])) for m in methods}


def comparisons(rows,trait):
    available = {m:[r for r in rows if r[f"{trait}_{m}_abs_error"] is not None] for m in METHODS}
    common = [r for r in rows if all(r[f"{trait}_{m}_abs_error"] is not None for m in METHODS)]
    paired = {}
    for comparator in ("A","B","C"):
        linked = [r for r in rows if r[f"{trait}_D_minus_{comparator}"] is not None]
        item = {"pair_n":len(linked),"paired_mae":mean_mae(linked,trait,(comparator,"D")),
                "ids":[r["tuber"] for r in linked],"mean_change":None,"median_change":None,
                "bootstrap_95":None,"wins":0,"ties":0,"losses":0}
        if linked:
            err = {m:np.asarray([r[f"{trait}_{m}_abs_error"] for r in linked]) for m in (comparator,"D")}
            draws = np.random.default_rng(prep.SEED).integers(len(linked),size=(DRAWS,len(linked)))
            stats = baseline.compare("D",comparator,err,draws)
            item.update({
                "mean_change":stats["mean_change_g"],"median_change":stats["median_change_g"],
                "bootstrap_95":stats["bootstrap_95_g"],"wins":stats["wins"],"ties":stats["ties"],"losses":stats["losses"],
            })
        paired[f"D_vs_{comparator}"] = item
    return {
        "unit":UNITS[trait],"enrolled":len(rows),"complete_four_n":len(common),
        "complete_four_ids":[r["tuber"] for r in common],"complete_four_mae":mean_mae(common,trait,METHODS),
        "scorable_counts":{m:len(v) for m,v in available.items()},
        "available_mae":{m:mean_mae(v,trait,(m,))[m] for m,v in available.items()},
        "paired":paired,
    }


def runtime_summary(rows):
    components = rows[0]["runtime_s"]
    summary = {}
    for label in ("train","val"):
        subset = [r for r in rows if r["split"]==label]
        t = {name:sum(r["runtime_s"][name] for r in subset) for name in components}
        a = t["center_support_s"]+t["center_feature_s"]
        b = a+t["outer_support_s"]+t["outer_feature_s"]
        full = sum(t[k] for k in ("center_support_s","outer_support_s","intermediate_support_s"))
        c = full+t["C_fit_fuse_feature_s"]
        d = full+t["D_fit_fuse_feature_s"]+t["D_flow_s"]
        totals = dict(zip(METHODS,(a,b,c,d),strict=True))
        summary[label] = {"enrolled":len(subset),"component_s":t,"method_total_s":totals,
                          "incremental_s_vs_A":{m:v-a for m,v in totals.items()},
                          "D_minus_C_s":d-c,"archive_reused_single_views":sum(
                              bool(v and v["archive_reused"]) for r in subset for v in r["single_views"].values())}
    return summary


def score():
    freeze = verify_analysis()
    if (prep.STUDY/"results.json").exists():
        raise FileExistsError("The study has already been scored")
    run,features = verified_features(freeze)
    fit_row = prep.pilot.read_json(prep.STUDY/"train_fit.json")
    predictions = prep.pilot.read_json(prep.STUDY/"predictions_before_targets.json")
    if (predictions["train_fit_sha256"]!=hash_at("train_fit.json")
            or fit_row["analysis_freeze_sha256"]!=hash_at("analysis_freeze.json")
            or fit_row["feature_run_sha256"]!=prep.pilot.digest(prep.OUTPUTS/"feature_run.json")):
        raise ValueError("Fits, predictions and feature inputs do not match")
    evaluation = [r for r in features if r["split"]=="val"]
    if predictions["predictions"]!=make_predictions(evaluation,fit_row["models"]):
        raise ValueError("Saved predictions differ from frozen fits")
    measured = reference(row["tuber"] for row in evaluation)
    individual = []
    scoring_failures = []
    for data,pred in zip(evaluation,predictions["predictions"],strict=True):
        tuber = data["tuber"]
        unit_row = {"tuber":tuber,"lower_suffix":data["selected"][0],"center_suffix":data["selected"][1],
                    "upper_suffix":data["selected"][2],
                    **{f"proxy_{m}_cm3":data["features"][m] for m in METHODS},
                    **{f"{m}_failure":data["registration"][m]["failure"] for m in ("C","D")},
                    **data["runtime_s"]}
        for trait in TRAITS:
            actual = measured[tuber][trait]
            unit_row[f"{trait}_measured"] = actual
            for method in METHODS:
                estimate = pred["prediction"][trait][method]
                unit_row[f"{trait}_{method}_prediction"] = estimate
                unit_row[f"{trait}_{method}_abs_error"] = abs(estimate-actual) if actual is not None and estimate is not None else None
                if unit_row[f"{trait}_{method}_abs_error"] is None:
                    scoring_failures.append({"tuber":tuber,"trait":trait,"method":method,
                                             "reason":"missing measurement" if actual is None else "missing feature"})
            for method in ("A","B","C"):
                a,b = [unit_row[f"{trait}_{m}_abs_error"] for m in (method,"D")]
                unit_row[f"{trait}_D_minus_{method}"] = b-a if a is not None and b is not None else None
        individual.append(unit_row)
    summary = {
        "training_n":fit_row["training_enrolled"],"evaluation_n":len(evaluation),
        "training_complete":{key:len(ids) for key,ids in fit_row["training_ids"].items()},
        "model_fit_wall_s":fit_row["fit_wall_s"],"checkpoint_setup_s":run["model_setup_s"],
        "registration_or_support_failure_records":run["failure_count"],"scoring_failures":scoring_failures,
        "runtime":runtime_summary(features),
        "outcomes":{trait:comparisons(individual,trait) for trait in TRAITS},
        "bootstrap_draws":DRAWS,"bootstrap_seed":prep.SEED,
        "prediction_sha256":hash_at("predictions_before_targets.json"),
    }
    baseline.write_csv(prep.STUDY/"per_potato.csv",individual)
    prep.pilot.write_json(prep.STUDY/"results.json",summary)
    for trait,item in summary["outcomes"].items():
        print(trait,item["complete_four_mae"],{k:v["bootstrap_95"] for k,v in item["paired"].items()},flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("freeze","fit","score"))
    args=parser.parse_args()
    {"freeze":seal_analysis,"fit":fit,"score":score}[args.stage]()
