
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Load CSV
df = pd.read_csv("/Users/ssy/Desktop/nus/dss5105-proj/text-encoders/results/compare_head_runs.csv")

# Clean column names if necessary
df.columns = (
    df.columns
    .str.replace("**", "", regex=False)
    .str.strip()
)

# Convert metrics to numeric
metrics = [
    "accuracy",
    "macro_f1",
    "f1_needs_action",
    "f1_needs_reply",
    "f1_reminder",
    "f1_no_immediate_action"
]

df[metrics] = df[metrics].apply(
    pd.to_numeric, errors="coerce"
)

sns.set_theme(style="whitegrid", context="talk")

# Average over seeds
summary = (
    df.groupby(["encoder", "condition"], as_index=False)
    [["accuracy", "macro_f1"]]
    .mean()
)

fig, axes = plt.subplots(1, 2, figsize=(15, 5))

for ax, metric, title in zip(
    axes,
    ["accuracy", "macro_f1"],
    ["Accuracy", "Macro-F1"]
):
    sns.barplot(
        data=summary,
        x="encoder",
        y=metric,
        hue="condition",
        hue_order=["real", "real+syn"],
        palette=["#4C78A8", "#F58518"],
        errorbar=None,
        ax=ax
    )

    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Encoder")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1)
    ax.tick_params(axis="x", rotation=15)

    for container in ax.containers:
        ax.bar_label(
            container,
            fmt="%.3f",
            padding=3,
            fontsize=10
        )

    ax.legend(title="Training Data")

plt.suptitle(
    "Impact of Synthetic Data Augmentation",
    fontsize=17,
    fontweight="bold"
)

plt.tight_layout()
plt.savefig("encoder_comparison.png", dpi=300, bbox_inches="tight")
plt.show()
