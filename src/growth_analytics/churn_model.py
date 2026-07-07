"""Predict which monthly subscribers will cancel before their first renewal.

Scoring point: day 14 of the subscription (features from sql/07_churn_features.sql).
Validation is out of time: train on subscriptions that started before September 2025,
test on later ones.

The read-out ends with a targeting rule for a retention offer, chosen by expected
value (assumptions in config.OFFER).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, precision_recall_curve,
                             roc_auc_score, roc_curve)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, OrdinalEncoder, StandardScaler

from . import config as C

TARGET = "churned_first_renewal"
COUNT_FEATURES = ["trial_workouts", "workouts_wk1", "workouts_wk2", "workouts_14d", "workouts_started_14d",
                  "active_days_14d", "sessions_14d", "crashes_14d", "days_since_last_active",
                  "days_signup_to_subscribe"]
SIGNED_FEATURES = ["workout_trend"]
NUMERIC = COUNT_FEATURES + SIGNED_FEATURES
CATEGORICAL = ["platform", "acquisition_channel", "region", "age_band", "device_tier"]
FEATURES = NUMERIC + CATEGORICAL
SPLIT_DATE = pd.Timestamp("2025-09-01")


def make_models(seed: int = 0) -> dict[str, Pipeline]:
    logit = Pipeline([
        ("prep", ColumnTransformer([
            ("counts", Pipeline([("log1p", FunctionTransformer(np.log1p, feature_names_out="one-to-one")), ("scale", StandardScaler())]), COUNT_FEATURES),
            ("signed", StandardScaler(), SIGNED_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), CATEGORICAL),
        ])),
        ("clf", LogisticRegression(C=0.5, max_iter=2000)),
    ])
    gbm = Pipeline([
        ("prep", ColumnTransformer([
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), CATEGORICAL),
            ("num", "passthrough", NUMERIC),
        ])),
        ("clf", HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=250, max_leaf_nodes=15, min_samples_leaf=40,
            l2_regularization=1.0, categorical_features=list(range(len(CATEGORICAL))), random_state=seed)),
    ])
    return {"Logistic regression": logit, "Gradient boosting": gbm}


def offer_value(df: pd.DataFrame, p: np.ndarray, y: np.ndarray | None = None) -> np.ndarray:
    """Expected (or realised, if y is given) value of offering the discount to each user."""
    o = C.OFFER
    fee = df["platform"].map(C.STORE_FEE).to_numpy()
    saved_value = o["extra_months_if_saved"] * C.PRICES["monthly"] * (1 - fee) - o["discount_usd"]
    wasted = o["redeem_rate_non_churners"] * o["discount_usd"]
    churn = p if y is None else y
    return churn * o["save_rate"] * saved_value - (1 - churn) * wasted


@dataclass
class ChurnResult:
    summary: dict
    curves: dict = field(default_factory=dict)
    calibration: pd.DataFrame | None = None
    deciles: pd.DataFrame | None = None
    importance: pd.DataFrame | None = None
    coefficients: pd.DataFrame | None = None
    policy_sweep: pd.DataFrame | None = None


def run(features: pd.DataFrame, seed: int = 0) -> ChurnResult:
    df = features.copy()
    df["start_date"] = pd.to_datetime(df["start_date"])
    train, test = df[df["start_date"] < SPLIT_DATE], df[df["start_date"] >= SPLIT_DATE]
    Xtr, ytr, Xte, yte = train[FEATURES], train[TARGET].to_numpy(), test[FEATURES], test[TARGET].to_numpy()

    models = make_models(seed)
    cv = StratifiedKFold(5, shuffle=True, random_state=seed)
    summary: dict = {"n_train": len(train), "n_test": len(test), "base_rate_train": float(ytr.mean()),
                     "base_rate_test": float(yte.mean()), "split_date": str(SPLIT_DATE.date()), "models": {}}
    preds, oof = {}, {}
    for name, m in models.items():
        oof[name] = cross_val_predict(m, Xtr, ytr, cv=cv, method="predict_proba")[:, 1]
        m.fit(Xtr, ytr)
        preds[name] = m.predict_proba(Xte)[:, 1]
        summary["models"][name] = {
            "cv_roc_auc": float(roc_auc_score(ytr, oof[name])),
            "test_roc_auc": float(roc_auc_score(yte, preds[name])),
            "test_pr_auc": float(average_precision_score(yte, preds[name])),
            "test_brier": float(brier_score_loss(yte, preds[name])),
        }
    # model selection uses cross-validation on the training period only
    best = max(models, key=lambda n: summary["models"][n]["cv_roc_auc"])
    summary["selected_model"] = best
    p = preds[best]

    curves = {}
    for name, pr in preds.items():
        fpr, tpr, _ = roc_curve(yte, pr)
        prec, rec, _ = precision_recall_curve(yte, pr)
        curves[name] = {"fpr": fpr, "tpr": tpr, "precision": prec, "recall": rec}

    frac_pos, mean_pred = calibration_curve(yte, p, n_bins=10, strategy="quantile")
    calib = pd.DataFrame({"mean_predicted": mean_pred, "observed_rate": frac_pos})

    dec = pd.DataFrame({"p": p, "y": yte})
    dec["decile"] = 10 - pd.qcut(dec["p"].rank(method="first"), 10, labels=False)  # 1 = riskiest
    deciles = dec.groupby("decile").agg(users=("y", "size"), churn_rate=("y", "mean"), avg_score=("p", "mean")).reset_index()
    deciles["lift"] = deciles["churn_rate"] / yte.mean()
    deciles["cum_capture"] = dec.sort_values("p", ascending=False)["y"].cumsum().to_numpy()[
        (deciles["users"].cumsum() - 1).to_numpy()] / yte.sum()
    summary["top_decile_lift"] = float(deciles.loc[deciles["decile"] == 1, "lift"].iloc[0])
    summary["top_30pct_capture"] = float(deciles.loc[deciles["decile"] == 3, "cum_capture"].iloc[0])

    imp = permutation_importance(models[best], Xte, yte, scoring="roc_auc", n_repeats=15, random_state=seed)
    importance = (pd.DataFrame({"feature": FEATURES, "importance": imp.importances_mean, "std": imp.importances_std})
                  .sort_values("importance", ascending=False).reset_index(drop=True))

    lr = models["Logistic regression"]
    names = lr.named_steps["prep"].get_feature_names_out()
    coefs = pd.DataFrame({"feature": names, "coef": lr.named_steps["clf"].coef_[0]})
    coefs["odds_ratio"] = np.exp(coefs["coef"])
    coefs = coefs.reindex(coefs["coef"].abs().sort_values(ascending=False).index).reset_index(drop=True)

    # targeting policy: choose the threshold on out-of-fold train predictions,
    # then report what it would have earned on the test period
    thresholds = np.round(np.arange(0.05, 0.91, 0.01), 2)
    val_tr = offer_value(train, oof[best], ytr)  # realised value per user if targeted
    val_te = offer_value(test, p, yte)
    sweep = []
    for th in thresholds:
        sel_tr, sel_te = oof[best] >= th, p >= th
        sweep.append({"threshold": th, "train_value_per_1k": 1000 * val_tr[sel_tr].sum() / len(train),
                      "test_value_per_1k": 1000 * val_te[sel_te].sum() / len(test),
                      "share_targeted_test": sel_te.mean()})
    sweep = pd.DataFrame(sweep)
    best_th = float(sweep.loc[sweep["train_value_per_1k"].idxmax(), "threshold"])
    row = sweep[sweep["threshold"] == best_th].iloc[0]
    o = C.OFFER
    net_share = float((1 - test["platform"].map(C.STORE_FEE)).mean())  # blended store fee
    gain = o["save_rate"] * (o["extra_months_if_saved"] * C.PRICES["monthly"] * net_share - o["discount_usd"])
    loss = o["redeem_rate_non_churners"] * o["discount_usd"]
    breakeven = loss / (gain + loss)  # target when P(churn) exceeds this
    summary["policy"] = {
        "threshold": best_th,
        "breakeven_probability": float(breakeven),
        "share_targeted": float(row["share_targeted_test"]),
        "value_per_1k_model": float(row["test_value_per_1k"]),
        "value_per_1k_target_all": float(1000 * val_te.sum() / len(test)),
        "value_per_1k_target_none": 0.0,
        "assumptions": dict(o),
    }
    summary["policy"]["uplift_vs_target_all"] = (summary["policy"]["value_per_1k_model"]
                                                 - summary["policy"]["value_per_1k_target_all"])
    return ChurnResult(summary, curves, calib, deciles, importance, coefs, sweep)
