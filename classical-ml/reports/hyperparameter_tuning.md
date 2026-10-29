# Hyperparameter tuning

Tuning uses 5x5 repeated stratified CV on the real training split only. The holdout is a one-off sanity check for the best configuration and is not used for selection.

## email_category

| Model | ngram | min_df | max_df | sublinear | C/alpha | CV Macro-F1 | CV Acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| linear_svm | (1, 2) | 2 | 0.98 | False | 10.0 | 0.906 ± 0.015 | 0.909 |
| linear_svm | (1, 2) | 2 | 0.9 | False | 10.0 | 0.906 ± 0.015 | 0.909 |
| linear_svm | (1, 2) | 2 | 0.9 | True | 1.0 | 0.904 ± 0.012 | 0.909 |
| linear_svm | (1, 2) | 2 | 0.98 | True | 1.0 | 0.904 ± 0.012 | 0.909 |
| linear_svm | (1, 1) | 2 | 0.98 | True | 10.0 | 0.901 ± 0.030 | 0.907 |
| linear_svm | (1, 1) | 2 | 0.9 | True | 10.0 | 0.901 ± 0.030 | 0.907 |
| logistic_regression | (1, 1) | 1 | 0.98 | True | 1.0 | 0.901 ± 0.016 | 0.907 |
| logistic_regression | (1, 1) | 1 | 0.9 | True | 1.0 | 0.901 ± 0.016 | 0.907 |
| linear_svm | (1, 2) | 2 | 0.9 | False | 1.0 | 0.901 ± 0.014 | 0.903 |
| linear_svm | (1, 2) | 2 | 0.98 | False | 1.0 | 0.901 ± 0.014 | 0.903 |

## required_action

| Model | ngram | min_df | max_df | sublinear | C/alpha | CV Macro-F1 | CV Acc |
|---|---:|---:|---:|---:|---:|---:|---:|
| complement_nb_balanced | (1, 2) | 1 | 0.9 | True | 3.0 | 0.688 ± 0.031 | 0.820 |
| complement_nb_balanced | (1, 2) | 1 | 0.98 | True | 3.0 | 0.686 ± 0.029 | 0.818 |
| complement_nb_balanced | (1, 2) | 1 | 0.9 | True | 1.0 | 0.662 ± 0.031 | 0.826 |
| complement_nb_balanced | (1, 2) | 1 | 0.98 | True | 1.0 | 0.659 ± 0.024 | 0.824 |
| complement_nb_balanced | (1, 1) | 1 | 0.9 | True | 1.0 | 0.649 ± 0.041 | 0.828 |
| complement_nb_balanced | (1, 1) | 1 | 0.98 | True | 1.0 | 0.649 ± 0.041 | 0.828 |
| complement_nb_balanced | (1, 1) | 2 | 0.98 | True | 3.0 | 0.646 ± 0.021 | 0.837 |
| complement_nb_balanced | (1, 1) | 2 | 0.9 | True | 3.0 | 0.646 ± 0.021 | 0.837 |
| complement_nb_balanced | (1, 1) | 2 | 0.98 | False | 1.0 | 0.645 ± 0.037 | 0.848 |
| complement_nb_balanced | (1, 1) | 2 | 0.9 | False | 1.0 | 0.645 ± 0.037 | 0.848 |

## Best configuration per task

| Task | Model | CV Macro-F1 | CV Acc | Holdout Macro-F1 | Holdout Acc |
|---|---|---:|---:|---:|---:|
| email_category | linear_svm | 0.906 ± 0.015 | 0.909 | 0.833 | 0.889 |
| required_action | complement_nb_balanced | 0.688 ± 0.031 | 0.820 | 0.820 | 0.889 |
