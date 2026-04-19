# Krylov v3 — Session Handoff (April 16, 2026)
## Junhyeok Lee, Professor Shin's Lab, Yonsei University

> **For the next LLM:** This handoff continues directly from `HANDOFF_krylov_alista_april15.md`. The April 15 run ("ALISTA2, 60k steps") **completed** and was fully analyzed this session. The main outcome of April 16 was a **reversal of the working diagnosis** (see §3). Read §1–§4 first.

---

## 1. TL;DR — WHERE THE PROJECT STANDS

**ALISTA2 run finished at step 60,000.** Substantial improvement over the 3-block baseline:

| metric @ r=0.01 | 3-block (prev) | ALISTA2 (final) |
|---|---|---|
| F1 | 0.373 | 0.604 |
| precision | 0.232 | 0.466 |
| recall | 0.959 | 0.868 |
| nnz_model | 1,795 | 815 |
| obj_gap | — | 1.164× |

**But the diagnosis of the remaining gap has been overturned.** Structural diagnostics (threshold sweep + top-k + FP magnitude quantiles) showed:

- FP median magnitude at r=0.01 is **~9×10⁻³** (18× the penalty threshold) — **not** a near-threshold tail.
- Top-k F1 at k=|sklearn support|=429 is only **0.673** — ~33% of the top-ranked features disagree with sklearn.
- The last 22,500 training steps (step 37.5k → 60k) produced essentially identical metrics. Fully converged.

**Open question as of end-of-session:** Are the FPs *correlated substitutes* (arbitrary-but-valid different solution) or *genuine false discoveries* (structural error)? A correlation-substitute diagnostic was prepared but **not yet run**. This is the first thing to do in the next session.

---

## 2. WHAT HAPPENED IN THIS SESSION (April 16)

In order:

1. **Baseline establishment.** Parsed ALISTA2 notebook outputs + model source. Confirmed full training log, final paired eval, and coefficient-path plots were all present in `Experiment_krylov_v3_alista2__1_.ipynb`.

2. **First analysis: training curves + paired eval.** Identified that the ALISTA2 run achieved the patch-cascade's design goals (topk=1024 was primary contributor; nnz penalty + 9-step refinement secondary). Noted: (a) most gain banked by step 2k, full plateau by step ~30k; (b) `best.pt` saved at step 37,500, not 60k; (c) recall 0.85–0.90 across all λ but precision collapses at r<0.05 → "precision tail at low λ."

3. **External reviewer agreement (doc 2).** An external reviewer independently reached the same conclusion ("first result that looks solver-like, not just promising; remaining gap is over-selection"). My response flagged three refinements: the prev-checkpoint multi-threshold sweep already showed tail is NOT near-threshold; "effective depth mattered" is confounded (topk + nnz changed simultaneously); nnz penalty target is miscalibrated (1.57× sklearn by construction).

4. **External reviewer diagnostic suite (doc 3).** Reviewer proposed threshold sweep + top-k + FP magnitude quantiles. I agreed with the direction, added two refinements (top-k upper-bounded by recall; recall@2k diagnostic), provided implementation.

5. **Scatter plot + diagnostic code written and run.** Beta scatter was straightforward. Tail-structure diagnostic ran successfully on both step-60k and step-37500 checkpoints. **Results were surprising.**

6. **Tail-structure results (see §3 for interpretation).** The "near-threshold" hypothesis was **falsified**: FP median magnitude is ~9×10⁻³, not ~5×10⁻⁴. Top-k F1 only 0.673 → ranking is genuinely wrong for ~1/3 of the top features. This reshaped the entire next-steps picture.

7. **Correlation-substitute diagnostic designed.** The critical remaining question: are those misranked FPs correlated substitutes (arbitrary) or genuine errors (structural)? The code was provided at end of session but **not executed yet**. This is the single highest-value test to run next.

---

## 3. THE DIAGNOSIS REVERSAL (critical context)

### What we believed before this session

Remaining gap was "cloud of small cheap coefficients near zero." Fix: tighten nnz-penalty target (`P·0.15·(1−√r)` → `P·0.10·(1−√r)` or closer to 1.1× sklearn nnz). OR: post-hoc hard threshold at inference. OR: add capacity (4 unique / 12 steps).

### What the tail-structure diagnostic showed

At step 60,000, r=0.01:

```
[1] Threshold sweep — F1 moves only 0.604 → 0.643 across thr = 1e-4 → 5e-3
    → tail is NOT near-threshold. Hard threshold at inference would gain
       only ~4 F1 points, not the "free win" we hoped for.

[2] Top-k @ k=|sklearn|=429:  precision=0.673, recall=0.673, f1=0.673
    (precision=recall because k is matched; F1 upper-bounded by recall≈0.87)
    → if ranking were correct and only calibration was off, F1 would be
       0.85–0.95. At 0.673, roughly 33% of the top-429 features the model
       picks are genuinely wrong by sklearn's lights.

[3] Top-k @ 2×|sklearn|=858: recall=0.867
    → matches raw recall. Doubling k doesn't recover more true support.
    → interpretation: the true support the model misses isn't buried in
       ranks 430–858; it's genuinely diffuse in the tail.

[5] FP magnitude quantiles at r=0.01:
    median = 8.92e-03,  q90 = 0.024,  q99 = 0.041,  max = 0.067
    → median FP is 18× the nnz-penalty threshold.
    → FPs are roughly 5–15% the magnitude of dominant true betas (~0.15–0.25).
    → These are NOT a cloud of tiny extras near zero. The model genuinely
       commits to these features with non-trivial magnitude.
```

**r=0.005 shows the same picture**: FP median 9.3e-3, q90 0.024, top-k F1 0.650.

**best.pt (step 37,500) vs step-60k are functionally indistinguishable** (all metrics differ by <0.01). The model is fully converged.

### What this overturns

1. **"Near-threshold" hypothesis: dead.** Hard inference threshold won't close the gap.
2. **"Tighten nnz target" prescription: dead.** The penalty's sigmoid at temperature=1e-4 already counts anything >1e-3 as fully active. Median FP at 9e-3 is already being counted as a full nonzero. Penalty is saturated on these features; the model simply prefers to keep them.
3. **"More training" / "more capacity" prescriptions: weakened.** ALISTA weight-shared blocks iterated 9× may converge to a "both on at half strength" fixed point for correlated pairs — more iterations of the same dynamical system won't necessarily escape it.
4. **"Fast screening model" framing: needs calibration.** Top-k at 2×|sklearn| only captures 87% recall. Screening would need k ≈ 3×|sklearn| or explicit post-processing.

### What the open question is

Given high correlation in `sync21` data, sklearn's choice among correlated features is partly arbitrary. If the model's "wrong" top-429 features are highly correlated with sklearn's chosen 429 (but different members of the same groups), then:

- F1 **overstates** the error.
- Model's solution is as good as sklearn's, just parameterized differently.
- Screen-then-solve would HURT recall.
- Don't add a correlation-repulsion term.

If instead the model's "wrong" features are weakly correlated with any true-active feature:

- F1 is correct; the model is genuinely confused.
- Screen-then-solve is the right move.
- Correlation-repulsion loss term is warranted.

**This is a one-cell diagnostic that we wrote at end of session but didn't run.** The code is in §6 of this handoff.

---

## 4. FILES AND CURRENT STATE

### Files needed to continue (user must re-upload these)

1. **This handoff** (`HANDOFF_krylov_alista_april16.md`)
2. **The April 15 handoff** (`HANDOFF_krylov_alista_april15.md`) — original project context. If this isn't available, the April 16 handoff references are still coherent but the deep background is lost.
3. **`model_krylov_v3_alista1.py`** — the current model source (2,092 lines, all 5 patches applied, ALISTA weight-sharing). Not modified this session.
4. **`Experiment_krylov_v3_alista2__1_.ipynb`** — contains:
   - Full 60k-step training log (cell 12 outputs)
   - Training curve plots (cell 14)
   - Frozen paired eval table at step 60k (cell 16)
   - Coefficient-path plots (cell 18)
   - Final summary (cell 20)
   - Scatter plot code added this session (`05_scatter.png`)
   - Tail-structure diagnostic cell added this session
   - Correlation-substitute diagnostic cell written (NOT YET EXECUTED)

### Optional but helpful

- Training-curve plot image (`loss_curve_alista1_60k.png`) — shows the plateau dynamics
- Coefficient-paths plot image (`lambda_parth_alista1_60k.png`) — shows paths are qualitatively correct
- External reviewer docs (the two plaintext documents embedded in the April 16 session; they contain the reviewer's framing that I partially agreed/disagreed with)

### On the server (Vast.ai instance, referenced by notebook)

- `/users/junhyeok/ckpt_krylov_v3_alista2/best.pt` — step 37,500, sel_sparse=0.264
- `/users/sync_data/generated/sync21_n500_p5k/` — ~100 GB, P=5k shards
- `/users/junhyeok/model_krylov_v3.py` — imported by notebook

### Checkpoints (in priority order for next work)

- **Primary**: `ckpt_krylov_v3_alista2/best.pt` (step 37,500) — use this for all downstream evaluations
- Older: `ckpt_krylov_v3_refine/best.pt` (3-block, step 8,500) — for baseline comparisons
- Older: `ckpt_krylov_v3_p5k_fast/best.pt` (pre-patch Phase 2)
- Oldest: `ckpt_krylov_v3/best.pt` (Phase 1, P=50)

---

## 5. COMPLETE RESULTS TABLE

### Final ALISTA2 paired eval (8 tasks, step 60,000)

| r | obj_gap | nnz_model | nnz_sklearn | β_corr | F1 | prec | rec |
|---|---|---|---|---|---|---|---|
| 0.900 | 1.0000 | 2.00 | 1.88 | 0.9997 | 0.944 | 0.938 | 0.975 |
| 0.500 | 1.0002 | 16.25 | 16.50 | 0.9855 | 0.917 | 0.906 | 0.931 |
| 0.200 | 1.0015 | 92.38 | 83.50 | 0.9773 | 0.857 | 0.807 | 0.925 |
| 0.100 | 1.0052 | 202.38 | 154.25 | 0.9607 | 0.802 | 0.720 | 0.924 |
| 0.050 | 1.0182 | 359.38 | 247.00 | 0.9144 | 0.729 | 0.614 | 0.897 |
| 0.020 | 1.0771 | 587.38 | 373.00 | 0.8307 | 0.659 | 0.541 | 0.845 |
| **0.010** | **1.1640** | **815.25** | **428.75** | **0.7667** | **0.604** | **0.466** | **0.868** |
| 0.005 | 1.2730 | 1146.62 | 464.38 | 0.7037 | 0.519 | 0.366 | 0.896 |

Avg: obj_gap 1.067×, nnz_ratio 1.82×, F1 0.754, β_corr 0.892.

### Tail-structure diagnostic (both checkpoints, 8 tasks)

**Step 60,000:**

| r | raw F1 | topk F1 @ \|sklearn\| | FP median | FP q90 |
|---|---|---|---|---|
| 0.010 | 0.604 | 0.673 | 8.92e-03 | 0.024 |
| 0.005 | 0.519 | 0.650 | 9.31e-03 | 0.024 |

**Step 37,500 (best.pt):** essentially identical (differences all <0.01).

### Threshold sweep at r=0.01 (step 60k)

| thr | nnz | prec | rec | F1 |
|---|---|---|---|---|
| 1e-4 | 815 | 0.465 | 0.868 | 0.604 |
| 5e-4 | 778 | 0.478 | 0.852 | 0.611 |
| 1e-3 | 750 | 0.487 | 0.839 | 0.615 |
| 2e-3 | 715 | 0.502 | 0.826 | 0.623 |
| 5e-3 | 645 | 0.539 | 0.801 | 0.643 |

**Note:** F1 moves only 0.604 → 0.643 across 50× threshold range. Tail is NOT near-threshold.

### Historical trajectory

| Run | nnz@.01 | ratio | F1@.01 | Notes |
|---|---|---|---|---|
| Pre-patch (P=5k) | ~3,500 | ~8× | — | Catastrophic |
| 3-block refine (step 8.5k) | 1,795 | 4.2× | 0.373 | Saturated |
| **ALISTA2 (step 60k)** | **815** | **1.9×** | **0.604** | **Current, converged** |
| sklearn | 429 | 1.0× | 1.0 | Reference |

---

## 6. CODE: NEXT-STEP DIAGNOSTIC (WRITTEN, NOT RUN)

This should be the FIRST thing executed in the next session. Drop in as a new cell in `Experiment_krylov_v3_alista2__1_.ipynb` after the tail-structure diagnostic cell. Uses variables already in scope.

```python
## 10. Correlation-substitute diagnostic (are the FPs substitutes or genuine errors?)

import torch
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

RATIOS_CORR = [0.01, 0.005]
B_CORR = N_SK  # 8 tasks with cached sklearn betas

# ─────────────────────────────────────────────────────────────────────
# Recompute model + sklearn betas on matched grid
# ─────────────────────────────────────────────────────────────────────
model.eval()
with torch.no_grad():
    _, lm_c = compute_lambda_pair(X_eval[:B_CORR], y_eval[:B_CORR],
                                   ratio_range=(min(RATIOS_CORR), max(RATIOS_CORR)))
    rt = torch.tensor(RATIOS_CORR, device=device, dtype=torch.float32)
    lams_c = lm_c[:, None] * rt[None, :]
    with torch.autocast(device_type="cuda", dtype=amp_dtype, enabled=amp_enabled):
        bm_corr = model(X_eval[:B_CORR], y_eval[:B_CORR], lambdas=lams_c).float()  # (B,Q,P)

bs_corr = torch.stack(
    [torch.tensor(sklearn_betas[r][:B_CORR], device=device, dtype=torch.float32)
     for r in RATIOS_CORR],
    dim=1,
)

def fp_correlation_analysis(bm_q, bs_q, Xb, thr=1e-4, corr_cutoff=0.7):
    B, P = bm_q.shape
    per_task = []
    all_max_corr = []
    for b in range(B):
        Xc = Xb[b] - Xb[b].mean(dim=0, keepdim=True)
        Xc = Xc / (Xc.std(dim=0, keepdim=True).clamp_min(1e-12))
        N = Xc.shape[0]
        pred = bm_q[b].abs() > thr
        true = bs_q[b].abs() > thr
        fp = pred & ~true
        fn = ~pred & true
        tp = pred & true
        fp_idx = fp.nonzero(as_tuple=True)[0]
        true_idx = true.nonzero(as_tuple=True)[0]
        if fp_idx.numel() == 0 or true_idx.numel() == 0:
            per_task.append({"n_fp": int(fp.sum()), "n_true": int(true.sum()),
                             "n_tp": int(tp.sum()), "n_fn": int(fn.sum()),
                             "frac_substitute": float("nan"),
                             "frac_strong_sub": float("nan"),
                             "median_max_corr": float("nan")})
            continue
        Xfp = Xc[:, fp_idx]; Xtr = Xc[:, true_idx]
        corr = (Xfp.T @ Xtr) / float(N)
        max_abs_corr, argmax_true = corr.abs().max(dim=1)
        fn_idx = fn.nonzero(as_tuple=True)[0]
        if fn_idx.numel() > 0:
            Xfn = Xc[:, fn_idx]
            corr_fn = (Xfp.T @ Xfn) / float(N)
            max_abs_corr_fn = corr_fn.abs().max(dim=1).values
        else:
            max_abs_corr_fn = torch.zeros_like(max_abs_corr)
        frac_sub = (max_abs_corr >= corr_cutoff).float().mean().item()
        frac_strong_sub = (max_abs_corr >= 0.9).float().mean().item()
        frac_sub_of_fn = (max_abs_corr_fn >= corr_cutoff).float().mean().item() \
                        if fn_idx.numel() > 0 else float("nan")
        per_task.append({
            "n_fp": int(fp.sum()), "n_true": int(true.sum()),
            "n_tp": int(tp.sum()), "n_fn": int(fn.sum()),
            "frac_substitute": frac_sub,
            "frac_strong_sub": frac_strong_sub,
            "frac_sub_of_fn": frac_sub_of_fn,
            "median_max_corr": max_abs_corr.median().item(),
            "q75_max_corr": max_abs_corr.quantile(0.75).item(),
            "q90_max_corr": max_abs_corr.quantile(0.9).item(),
        })
        all_max_corr.append(max_abs_corr.cpu().numpy())
    return per_task, (np.concatenate(all_max_corr) if all_max_corr else np.array([]))

X_for_corr = X_eval[:B_CORR]
results_by_ratio = {}
for q, r in enumerate(RATIOS_CORR):
    print("\n" + "=" * 80)
    print(f"CORRELATION-SUBSTITUTE DIAGNOSTIC — r = {r}")
    print("=" * 80)
    per_task, all_mc = fp_correlation_analysis(
        bm_corr[:, q, :], bs_corr[:, q, :], X_for_corr, thr=1e-4, corr_cutoff=0.7)
    results_by_ratio[r] = (per_task, all_mc)
    df = pd.DataFrame(per_task); df.index.name = "task"
    print("\nPer-task breakdown:")
    with pd.option_context("display.float_format", lambda x: f"{x:.3f}",
                           "display.width", 140):
        print(df.to_string())
    n_fp_total = int(df["n_fp"].sum())
    if n_fp_total > 0:
        frac_sub_agg = (all_mc >= 0.7).mean()
        frac_strong_agg = (all_mc >= 0.9).mean()
        frac_random_agg = (all_mc < 0.5).mean()
        med_all = np.median(all_mc)
        print(f"\nAggregated across all {n_fp_total} FPs:")
        print(f"  median max|corr| : {med_all:.3f}")
        print(f"  q25/q50/q75/q90  : {np.quantile(all_mc, 0.25):.3f} / "
              f"{np.quantile(all_mc, 0.50):.3f} / {np.quantile(all_mc, 0.75):.3f} / "
              f"{np.quantile(all_mc, 0.90):.3f}")
        print(f"  frac ≥ 0.9 (strong substitute) : {frac_strong_agg:.1%}")
        print(f"  frac ≥ 0.7 (substitute)        : {frac_sub_agg:.1%}")
        print(f"  frac < 0.5 (genuine FP)        : {frac_random_agg:.1%}")
        print("\n  → VERDICT:")
        if frac_sub_agg >= 0.7:
            print(f"     {frac_sub_agg:.0%} of FPs are substitutes. F1 OVERSTATES error.")
            print(f"     → Do NOT screen-then-solve; do NOT add correlation-repulsion.")
        elif frac_sub_agg >= 0.4:
            print(f"     MIXED: {frac_sub_agg:.0%} substitutes, {frac_random_agg:.0%} genuine.")
            print(f"     → Both fixes apply partially.")
        else:
            print(f"     STRUCTURAL: only {frac_sub_agg:.0%} substitutes.")
            print(f"     → Screen-then-solve + correlation-repulsion both warranted.")

fig, axes = plt.subplots(1, 2, figsize=(12, 4))
for ax, r in zip(axes, RATIOS_CORR):
    all_mc = results_by_ratio[r][1]
    if all_mc.size == 0: continue
    ax.hist(all_mc, bins=40, range=(0, 1), color="C3", alpha=0.75, edgecolor="white")
    ax.axvline(0.7, color="k", ls="--", lw=1, alpha=0.6, label="substitute cutoff (0.7)")
    ax.axvline(0.9, color="k", ls=":", lw=1, alpha=0.6, label="strong substitute (0.9)")
    ax.axvline(np.median(all_mc), color="C0", lw=2, label=f"median = {np.median(all_mc):.2f}")
    ax.set_xlabel("max |corr(FP, any sklearn-active)|"); ax.set_ylabel("count")
    ax.set_title(f"r = {r}  ({len(all_mc)} FPs)"); ax.set_xlim(0, 1)
    ax.legend(fontsize=9, loc="upper left"); ax.grid(True, alpha=0.25)
fig.suptitle("FP correlation with sklearn-active support — substitutes or errors?", fontsize=12)
plt.tight_layout()
plt.savefig(FIG_DIR / "06_fp_correlation.png", dpi=150, bbox_inches="tight")
plt.show()

print("\n" + "=" * 80)
print("BONUS: Are substitute FPs specifically replacing missed (FN) sklearn features?")
print("=" * 80)
for q, r in enumerate(RATIOS_CORR):
    per_task, _ = results_by_ratio[r]
    df = pd.DataFrame(per_task)
    if "frac_sub_of_fn" in df.columns and df["n_fn"].sum() > 0:
        fsf = df["frac_sub_of_fn"].mean()
        print(f"  r={r}: frac of FPs correlated (≥0.7) with *FNs* = {fsf:.1%}")
        print(f"         (vs {df['frac_substitute'].mean():.1%} correlated with any true-active)")
        if fsf >= 0.5:
            print(f"    → Most FPs are swap-ins for missed features. BENIGN group-arbitrariness.")
        elif fsf >= 0.25:
            print(f"    → Some swap, but many FPs correlate with KEPT features. Mixed.")
        else:
            print(f"    → FPs correlate with KEPT features → OVER-SELECTION within groups.")

del bm_corr, bs_corr
gc.collect()
if device.type == "cuda":
    torch.cuda.empty_cache()
```

---

## 7. DECISION TREE FOR NEXT STEPS (ONCE DIAGNOSTIC RUNS)

The correlation-substitute diagnostic has four possible outcomes. Each has a different optimal response:

### Outcome A: `frac_substitute ≥ 0.7` AND `frac_sub_of_fn ≥ 0.5`

**Meaning:** Most FPs are swap substitutes for missed sklearn features. Model solution is different-but-valid.

**Response:**
- Stop treating F1 as the primary metric for the low-λ regime.
- Report β_corr and objective gap as primary; F1 as supplementary.
- Consider adding an optional sklearn-matching objective for reproducibility (but note this would be training toward an arbitrary anchor).
- The architecture is already effectively at sklearn's solver quality for this data.
- **Presentation framing:** "Matches sklearn's fit at low λ; disagrees only on which correlated feature to pick, which is an ill-posed choice."

### Outcome B: `frac_substitute ≥ 0.5` but `frac_sub_of_fn < 0.25` (OVER-SELECTION)

**Meaning:** FPs correlate with features sklearn KEPT, not features sklearn MISSED. Model is keeping BOTH members of correlated pairs instead of picking one.

**Response:**
- Add a **correlation-repulsion loss term**: `Σ βᵢβⱼ·corr(Xᵢ,Xⱼ)` for active pairs, weighted ~0.01–0.05.
- This is the most targeted fix: directly penalizes the "both on at half strength" fixed point that ALISTA weight-shared blocks can converge to.
- Minimal architecture change; can warm-start from existing checkpoint.

### Outcome C: `frac_substitute ∈ [0.4, 0.7]` (MIXED)

**Meaning:** Some group-arbitrariness, some genuine error. Common in high-correlation data.

**Response:**
- Run correlation-repulsion experiment (Outcome B response) to handle the over-selection portion.
- In parallel, set up screen-then-solve pipeline (neural top-K screen → sklearn refine) for the genuine-error portion.
- Compare both on paired eval.

### Outcome D: `frac_substitute < 0.4` (GENUINE STRUCTURAL)

**Meaning:** FPs are real false discoveries, weakly correlated with true support.

**Response:**
- Screen-then-solve is the strongly indicated path (handoff's original "Option A").
- Consider sklearn-teacher training on subset of data at low λ.
- Capacity increase (4 unique / 12 steps) is unlikely to help — more iterations of same dynamical system.
- The refinement architecture has hit its ceiling without a genuine selection mechanism (hard top-K, Gumbel gate, etc.).

---

## 8. SECONDARY ITEMS (LOWER PRIORITY)

These were flagged during the session but not blocking:

1. **Training-stability spikes.** KKT curve showed spikes at steps ~25k, ~30k, ~42–44k, plus a single-batch `loss=1630.83` at step ~57.6k (rescued by grad clip). Suggests peak LR 3×10⁻⁴ is on the high end for this 185K-param bf16 config. Future runs: try 1.5×10⁻⁴.

2. **Checkpoint vs final-state mismatch.** `best.pt` saved at step 37,500 but the paired-eval in the notebook ran on in-memory step-60k model. Re-evaluating from `best.pt` gives essentially identical results (tail-structure diagnostic confirmed this). Not a problem.

3. **Trainer has a bug:** `ckpt["epoch"]` in eval-only path should be `ckpt["step"]`. Noted in reviewer doc but not applied (notebook doesn't use eval-only path).

4. **The April 15 handoff's next-step predictions were wrong.** It predicted nnz@0.01 would reach <700 (Phase 2 "approaching solved"). Actual: 815. Still in the "add capacity" bucket per that decision tree, but the new diagnostics make that prescription obsolete — capacity won't fix what's genuinely broken.

5. **Multi-penalty extensions (Ridge, EN, SCAD, MCP) and P=10,000+ Phase 3** — both still on the long-term roadmap but gated on Phase 2 (P=5k) being solved/published first.

---

## 9. MODEL CONFIG (CURRENT CHECKPOINT)

```python
KrylovQueryDecoderConfig(
    krylov_dim=64,
    num_decoder_channels=12, use_bilinear_channels=True,
    cond_dim=32, cond_hidden=96, query_mixer_hidden=96,
    feature_head_hidden=160, prox_hidden=80,
    # Refinement (ALISTA: 3 unique blocks × 3 repeats)
    num_refinement_blocks=9, refinement_num_unique=3,
    refinement_hidden=96, refinement_n_global=6, zero_init_refinement=True,
    # Prox constraint (prevents globally-too-lenient shrinkage)
    prox_shift_min=-0.3, prox_shift_max=2.0,
    # KKT (scale-aware threshold + topk=1024 passed at loss call)
    kkt_beta_zero_tol=1e-3, kkt_scale_aware_tol=True, kkt_scale_tol_factor=0.01,
    # Smooth nnz penalty (saturated on current FPs; tightening target won't help)
    nnz_penalty_weight=0.05, nnz_penalty_threshold=5e-4, nnz_penalty_temperature=1e-4,
    # Required for refinement blocks
    retain_centered_data_in_encoding=True,
)
```

Training loss: `lasso_training_loss_v3` with `kkt_inactive_topk=1024` (passed at call site, not in config). Total params: 185,587 (143K one-shot + 42K refinement).

---

## 10. HOW TO RESUME

### Paste at the top of the new chat

> "I'm continuing the Krylov v3 project. The ALISTA2 run (60k steps) completed and I've done the tail-structure diagnostics. The findings overturned our working hypothesis — the FPs are NOT near-threshold; they have median magnitude ~9e-3. Top-k F1 at |sklearn support| is only 0.673. Before committing to a next step, I need to run the correlation-substitute diagnostic to determine whether those misranked FPs are correlated substitutes (arbitrary) or genuine errors (structural). See §3, §6, §7 of the handoff."

### Files to re-upload

**Minimum to continue:**

1. `HANDOFF_krylov_alista_april16.md` (this file)
2. `Experiment_krylov_v3_alista2__1_.ipynb` (with the outputs preserved)
3. `model_krylov_v3_alista1.py`

**Helpful context (strongly recommended):**

4. `HANDOFF_krylov_alista_april15.md` (the previous session's handoff)

**Optional:**

5. `loss_curve_alista1_60k.png` and `lambda_parth_alista1_60k.png` — visual context of training dynamics

### First action in new session

Run the correlation-substitute diagnostic cell (§6 of this handoff) on the `best.pt` checkpoint at step 37,500. Paste the full output to the LLM. Then use the §7 decision tree to choose the next experiment.

### Expected outcomes (my best guess before running)

Based on the fact that FPs have real magnitude (~9e-3, not threshold-level) AND high correlation is typical of `sync21` data:

- I'd give ~50% probability to **Outcome B** (over-selection within groups — frac_substitute high, frac_sub_of_fn low). This would mean correlation-repulsion loss is the targeted fix.
- ~30% to **Outcome C** (mixed).
- ~15% to **Outcome A** (pure group-arbitrariness — would mean the project is basically done at low λ and we're chasing a metric artifact).
- ~5% to **Outcome D** (pure structural error — unlikely given high correlation in the data).

Report the actual numbers and follow the decision tree regardless of prior.
