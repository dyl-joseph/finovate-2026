"""Fake-Supabase visualization of cross-call speaker re-identification.

Shows, for a synthetic set of calls stored in Supabase-style rows
(speaker_profiles / speaker_encounters), how the voice-embedding matcher
re-identifies repeat callers: which audio chunks get embedded, the cosine
similarity against known profiles, the 0.80 match gate, and the
REPEAT_FLAGGED_SPEAKER callouts that light up the evidence graph.

Outputs reid-visualization.png.
"""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

THRESHOLD = 0.80

# --- Fake Supabase rows ------------------------------------------------------------------
# speaker_profiles: what Supabase would hold after 6 calls
PROFILES = {
    "voice-profile-a": {"sample_count": 3, "last_seen": "call-0005"},
    "voice-profile-b": {"sample_count": 1, "last_seen": "call-0002"},
    "voice-profile-c": {"sample_count": 1, "last_seen": "call-0004"},
}

# speaker_encounters: one row per conversation
ENCOUNTERS = [
    {"conversation_id": "call-0001", "profile": "voice-profile-a", "risk": 78, "level": "high"},
    {"conversation_id": "call-0002", "profile": "voice-profile-b", "risk": 18, "level": "low"},
    {"conversation_id": "call-0003", "profile": "voice-profile-a", "risk": 100, "level": "critical"},
    {"conversation_id": "call-0004", "profile": "voice-profile-c", "risk": 24, "level": "low"},
    {"conversation_id": "call-0005", "profile": "voice-profile-a", "risk": 100, "level": "critical"},
]

# Calls: id, duration (s), caller chunks (start, end in seconds), and the
# per-profile similarity scores measured at re-id time (None = profile did not
# exist yet when this call was processed).
CALLS = [
    {
        "id": "call-0001",
        "duration": 92,
        "chunks": [(6, 14), (29, 38), (61, 70), (74, 84)],
        "sims": {"voice-profile-a": None, "voice-profile-b": None, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-a"),
        "repeat": False,
    },
    {
        "id": "call-0002",
        "duration": 55,
        "chunks": [(3, 12), (20, 27), (31, 47)],
        "sims": {"voice-profile-a": 0.34, "voice-profile-b": None, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-b"),
        "repeat": False,
    },
    {
        "id": "call-0003",
        "duration": 88,
        "chunks": [(5, 15), (25, 33), (58, 66), (71, 80)],
        "sims": {"voice-profile-a": 0.87, "voice-profile-b": 0.41, "voice-profile-c": None},
        "match": ("re-id", "voice-profile-a"),
        "repeat": True,
    },
    {
        "id": "call-0004",
        "duration": 64,
        "chunks": [(2, 9), (18, 26), (40, 55)],
        "sims": {"voice-profile-a": 0.29, "voice-profile-b": 0.45, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-c"),
        "repeat": False,
    },
    {
        "id": "call-0005",
        "duration": 99,
        "chunks": [(8, 18), (34, 42), (60, 69), (85, 93)],
        "sims": {"voice-profile-a": 0.92, "voice-profile-b": 0.37, "voice-profile-c": 0.52},
        "match": ("re-id", "voice-profile-a"),
        "repeat": True,
    },
]

PROFILE_COLORS = {
    "voice-profile-a": "#e4572e",
    "voice-profile-b": "#2e86ab",
    "voice-profile-c": "#3aa655",
}

fig = plt.figure(figsize=(15, 10))
fig.patch.set_facecolor("#0f1420")
gs = fig.add_gridspec(3, 1, height_ratios=[3, 2, 2], hspace=0.55,
                       left=0.06, right=0.97, top=0.92, bottom=0.07)
GS_FG = "#e8ecf4"
GS_MUTED = "#93a0b8"
GS_GRID = "#2a3450"

# ---------------------------------------------------------------- Panel 1: chunk timeline
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor("#0f1420")

first_sim_scores = []
for call_index, call in enumerate(CALLS):
    y = len(CALLS) - call_index
    # call duration track
    ax1.barh(y, call["duration"], left=0, height=0.42, color="#1b2336",
             edgecolor=GS_GRID, linewidth=1, zorder=1)
    is_repeat = call["repeat"]
    for i, (start, end) in enumerate(call["chunks"]):
        proto = call["match"][1]
        color = PROFILE_COLORS[proto] if is_repeat or call["match"][0] == "re-id" else "#5b6b8c"
        ax1.barh(y, end - start, left=start, height=0.42, color=color,
                 alpha=0.95 if is_repeat else 0.55, edgecolor="#0f1420", linewidth=0.6, zorder=2)
        # the chunk that pushes the matcher over the gate
        if is_repeat and i == 0:
            sim = call["sims"][proto]
            ax1.annotate(f"re-id: {sim:.0%} vs {proto.split('-')[-1]}",
                         xy=(start, y), xytext=(start + 1, y + 0.30),
                         fontsize=8.5, color="#ffd166", fontweight="bold",
                         arrowprops=dict(arrowstyle="-", color="#ffd166", lw=0.8))
    ax1.text(-4, y, call["id"], ha="right", va="center", fontsize=9,
             color=GS_FG, fontfamily="monospace")
    if is_repeat:
        ax1.scatter(call["duration"] + 3, y, marker="*", s=140, color="#ffd166",
                    edgecolor="black", linewidth=0.4, zorder=4)

# legend
legend_handles = [plt.Rectangle((0, 0), 1, 1, fc=color) for color in PROFILE_COLORS.values()]
ax1.legend(legend_handles, [p.split("-")[-1] for p in PROFILE_COLORS],
           loc="lower right", ncol=3, frameon=False, fontsize=9,
           labelcolor=GS_FG, title="matched voice profile", title_fontsize=9)
ax1.set_xlabel("seconds into call (caller speech windows = embedded chunks)",
               color=GS_MUTED, fontsize=9)
ax1.set_title("Which audio chunks get embedded, and where re-id fires",
              color=GS_FG, fontsize=13, fontweight="bold", loc="left", pad=12)
ax1.set_yticks([])
ax1.tick_params(colors=GS_MUTED, labelsize=8)
for spine in ax1.spines.values():
    spine.set_color(GS_GRID)

# --------------------------------------------------------------- Panel 2: similarity gate
ax2 = fig.add_subplot(gs[1])
ax2.set_facecolor("#0f1420")

known = sorted(PROFILE_COLORS.keys())
width = 0.22
for j, profile in enumerate(known):
    values = [call["sims"].get(profile) for call in CALLS]
    xs = [i + (j - 1) * width for i, value in enumerate(values) if value is not None]
    ys = [value for value in values if value is not None]
    ax2.bar(xs, ys, width=width, color=PROFILE_COLORS[profile],
            alpha=0.75, edgecolor="#0f1420", label="p-" + profile.split("-")[-1], zorder=2)

ax2.axhline(THRESHOLD, color="#ffd166", linestyle="--", linewidth=1.4, zorder=3)
ax2.text(4.45, THRESHOLD + 0.015, f"match gate = {THRESHOLD:.0%}",
         color="#ffd166", fontsize=9, ha="right", fontweight="bold")

for call_index, call in enumerate(CALLS):
    if call["match"][0] == "re-id":
        sim = call["sims"][call["match"][1]]
        ax2.annotate(f"call-{call_index+1:04d} {sim:.0%}\n→ re-identified",
                     xy=(call_index, sim), xytext=(call_index, sim + 0.10),
                     fontsize=8.5, color="#ffd166", fontweight="bold", ha="center",
                     arrowprops=dict(arrowstyle="->", color="#ffd166", lw=1))

ax2.set_xticks(range(len(CALLS)))
ax2.set_xticklabels([call["id"] for call in CALLS], fontsize=8, color=GS_MUTED, rotation=20)
ax2.set_ylim(0, 1.15)
ax2.set_ylabel("cosine similarity vs stored profile", color=GS_MUTED, fontsize=9)
ax2.set_title("Similarity to each profile vs the 0.80 gate (above = same person)",
              color=GS_FG, fontsize=13, fontweight="bold", loc="left", pad=12)
ax2.legend(frameon=False, fontsize=9, labelcolor=GS_FG, loc="upper left")
ax2.tick_params(colors=GS_MUTED, labelsize=8)
ax2.grid(axis="y", color=GS_GRID, linewidth=0.7, alpha=0.5)
for spine in ax2.spines.values():
    spine.set_color(GS_GRID)

# -------------------------------------------------------------- Panel 3: risk escalation
ax3 = fig.add_subplot(gs[2])
ax3.set_facecolor("#0f1420")

risk_values = [encounter["risk"] for encounter in ENCOUNTERS]
bar_colors = []
for encounter in ENCOUNTERS:
    if encounter["level"] == "critical":
        bar_colors.append("#e4572e")
    elif encounter["level"] == "high":
        bar_colors.append("#f4a259")
    else:
        bar_colors.append("#3f5d7a")

bars = ax3.bar(range(len(risk_values)), risk_values, color=bar_colors,
               edgecolor="#0f1420", zorder=2)
for call_index, (bar, encounter) in enumerate(zip(bars, ENCOUNTERS)):
    ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
             str(encounter["risk"]), ha="center", fontsize=10, color=GS_FG,
             fontweight="bold", fontfamily="monospace")
    if encounter["risk"] == 100:
        ax3.annotate(
            "REPEAT_FLAGGED_SPEAKER\n+25 risk · memory_finding node\n· prior_encounter node\n· matches_prior edge",
            xy=(call_index, 100), xytext=(call_index + 0.18, 62),
            fontsize=8, color="#ffd166",
            arrowprops=dict(arrowstyle="->", color="#ffd166", lw=1))

ax3.set_xticks(range(len(risk_values)))
ax3.set_xticklabels([encounter["conversation_id"] for encounter in ENCOUNTERS],
                    fontsize=8, color=GS_MUTED, rotation=20)
ax3.set_ylim(0, 120)
ax3.set_ylabel("risk score", color=GS_MUTED, fontsize=9)
ax3.set_title("Risk callouts: repeat-caller hits push the score to critical and add graph nodes",
              color=GS_FG, fontsize=13, fontweight="bold", loc="left", pad=12)
ax3.tick_params(colors=GS_MUTED, labelsize=8)
ax3.grid(axis="y", color=GS_GRID, linewidth=0.7, alpha=0.5)
for spine in ax3.spines.values():
    spine.set_color(GS_GRID)

fig.suptitle(
    "Speaker re-identification across calls  ·  fake rows mirroring Supabase "
    "(speaker_profiles / speaker_encounters)",
    color=GS_MUTED, fontsize=10, y=0.985,
)

fig.savefig("reid-visualization.png", dpi=150, facecolor="#0f1420", bbox_inches="tight")
print("saved reid-visualization.png")