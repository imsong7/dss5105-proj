# Model comparison

CV is 5x5 repeated stratified CV on real emails only; synthetic emails are added only to required_action training folds. The 27-email holdout is a sanity check and should not be used for model selection.

### email_category

| Model | CV Macro-F1 | CV Accuracy | Holdout Macro-F1 | Holdout Accuracy |
|---|---:|---:|---:|---:|
| complement_nb_balanced | 0.873 ± 0.021 | 0.886 ± 0.017 | 0.830 | 0.889 |
| logistic_regression | 0.865 ± 0.021 | 0.880 ± 0.017 | 0.831 | 0.889 |
| linear_svm | 0.861 ± 0.018 | 0.881 ± 0.016 | 0.833 | 0.889 |
| complement_nb | 0.823 ± 0.018 | 0.862 ± 0.016 | 0.830 | 0.889 |
| xgboost | 0.795 ± 0.024 | 0.806 ± 0.023 | 0.738 | 0.778 |
| random_forest | 0.768 ± 0.016 | 0.800 ± 0.013 | 0.739 | 0.778 |
| multinomial_nb | 0.660 ± 0.012 | 0.752 ± 0.011 | 0.672 | 0.778 |
| majority_baseline | 0.082 ± 0.000 | 0.258 ± 0.000 | 0.082 | 0.259 |

### required_action

| Model | CV Macro-F1 | CV Accuracy | Holdout Macro-F1 | Holdout Accuracy |
|---|---:|---:|---:|---:|
| complement_nb_balanced | 0.697 ± 0.023 | 0.812 ± 0.008 | 0.820 | 0.889 |
| complement_nb | 0.672 ± 0.029 | 0.821 ± 0.014 | 0.820 | 0.889 |
| linear_svm | 0.653 ± 0.049 | 0.825 ± 0.021 | 0.726 | 0.852 |
| xgboost | 0.592 ± 0.034 | 0.743 ± 0.015 | 0.492 | 0.778 |
| random_forest | 0.557 ± 0.019 | 0.809 ± 0.007 | 0.518 | 0.778 |
| multinomial_nb | 0.551 ± 0.049 | 0.809 ± 0.020 | 0.471 | 0.815 |
| logistic_regression | 0.547 ± 0.043 | 0.808 ± 0.006 | 0.336 | 0.741 |
| majority_baseline | 0.211 ± 0.000 | 0.732 ± 0.000 | 0.213 | 0.741 |
