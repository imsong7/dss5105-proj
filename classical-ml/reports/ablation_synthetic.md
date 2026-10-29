# Synthetic data ablation (required_action)

Real emails: 134; synthetic rows: 200; CV: 5x5 repeated stratified on real emails.

| Model | Real-only Macro-F1 | + Synthetic Macro-F1 | Delta | + Synthetic Accuracy |
|---|---:|---:|---:|---:|
| complement_nb | 0.403 ± 0.014 | 0.672 ± 0.029 | +0.270 | 0.821 ± 0.014 |
| complement_nb_balanced | 0.440 ± 0.034 | 0.697 ± 0.023 | +0.257 | 0.812 ± 0.008 |
| linear_svm | 0.421 ± 0.022 | 0.653 ± 0.049 | +0.231 | 0.825 ± 0.021 |
