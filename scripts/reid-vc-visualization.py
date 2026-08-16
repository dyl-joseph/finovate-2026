"""VC-facing visualization: cross-call caller recognition on fake Supabase rows.

Transparent background, no overlapping labels. Same scenario as before:
five interactions, one impersonation ring recognized by voice.
Outputs reid-vc-visualization.png.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

THRESHOLD = 0.80

PROFILES = {
    "voice-profile-a": {"sample_count": 3, "last_seen": "call-0005"},
    "voice-profile-b": {"sample_count": 1, "last_seen": "call-0002"},
    "voice-profile-c": {"sample_count": 1, "last_seen": "call-0004"},
}

ENCOUNTERS = [
    {"conversation_id": "call-0001", "profile": "voice-profile-a", "risk": 78, "level": "high"},
    {"conversation_id": "call-0002", "profile": "voice-profile-b", "risk": 18, "level": "low"},
    {"conversation_id": "call-0003", "profile": "voice-profile-a", "risk": 100, "level": "critical"},
    {"conversation_id": "call-0004", "profile": "voice-profile-c", "risk": 24, "level": "low"},
    {"conversation_id": "call-0005", "profile": "voice-profile-a", "risk": 100, "level": "critical"},
]

CALLS = [
    {
        "id": "call-0001", "duration": 92,
        "chunks": [(6, 14), (29, 38), (61, 70), (74, 84)],
        "sims": {"voice-profile-a": None, "voice-profile-b": None, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-a"), "repeat": False,
        "attempted": 2000,
    },
    {
        "id": "call-0002", "duration": 55,
        "chunks": [(3, 12), (20, 27), (31, 47)],
        "sims": {"voice-profile-a": 0.34, "voice-profile-b": None, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-b"), "repeat": False,
        "attempted": 0,
    },
    {
        "id": "call-0003", "duration": 88,
        "chunks": [(5, 15), (25, 33), (58, 66), (71, 80)],
        "sims": {"voice-profile-a": 0.87, "voice-profile-b": 0.41, "voice-profile-c": None},
        "match": ("re-id", "voice-profile-a"), "repeat": True,
        "attempted": 2000,
    },
    {
        "id": "call-0004", "duration": 64,
        "chunks": [(2, 9), (18, 26), (40, 55)],
        "sims": {"voice-profile-a": 0.29, "voice-profile-b": 0.45, "voice-profile-c": None},
        "match": ("enroll", "voice-profile-c"), "repeat": False,
        "attempted": 0,
    },
    {
        "id": "call-0005", "duration": 99,
        "chunks": [(8, 18), (34, 42), (60, 69), (85, 93)],
        "sims": {"voice-profile-a": 0.92, "voice-profile-b": 0.37, "voice-profile-c": 0.52},
        "match": ("re-id", "voice-profile-a"), "repeat": True,
        "attempted": 2000,
    },
]

PROFILE_COLORS = {
    "voice-profile-a": "#d1495b",
    "voice-profile-b": "#30638e",
    "voice-profile-c": "#4c9f70",
}

BG = "none"
FG = "#1d2733"
MUTED = "#5d6b7e"
GRID = "#dfe5ee"
ACCENT = "#d1495b"
HIGHLIGHT = "#b8860b"

fig = plt.figure(figsize=(15, 10.5), facecolor=BG)
gs = fig.add_gridspec(3, 1, height_ratios=[3, 2, 2], hspace=0.55,
                       left=0.07, right=0.97, top=0.78, bottom=0.06)

# ------------------------------------------------------------ header stats strip
fig.text(0.07, 0.94, "Cross-call caller recognition", fontsize=20,
         fontweight="bold", color=FG)
fig.text(0.07, 0.90, "Five interactions, one impersonation ring. The system identifies the actor "
                     "by voice — not by phone number, which scammers spoof.",
         fontsize=11.5, color=MUTED)

stats = [
    ("2 / 5", "calls recognized\nas repeat actors"),
    ("3", "voiceprints on file,\nstrengthened each call"),
    ("$6,000", "in transfer attempts\nstopped"),
    ("0.80", "min confidence bar\nfor claiming a match"),
]
panel_w = 0.215
for i, (number, caption) in enumerate(stats):
    x = 0.07 + i * (panel_w + 0.012)
    box = fig.add_axes([x, 0.795, panel_w, 0.078])
    box.set_facecolor(BG)
    for spine in box.spines.values():
        spine.set_color(GRID)
    box.axis("off")
    box.text(0.5, 0.66, number, ha="center", va="center", fontsize=17,
             fontweight="bold", color=ACCENT, transform=box.transAxes)
    box.text(0.5, 0.22, caption, ha="center", va="center", fontsize=8.2,
             color=MUTED, transform=box.transAxes, linespacing=1.3)

# ---------------------------------------------------------------- Panel 1: recognition
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor(BG)

for call_index, call in enumerate(CALLS):
    y = len(CALLS) - call_index
    ax1.barh(y, call["duration"], left=0, height=0.4, color="#eef2f7",
             edgecolor=GRID, linewidth=1, zorder=1)
    is_repeat = call["repeat"]
    profile = call["match"][1]
    color = PROFILE_COLORS[profile] if is_repeat else "#aeb9c8"
    for start, end in call["chunks"]:
        ax1.barh(y, end - start, left=start, height=0.4, color=color,
                 alpha=0.9 if is_repeat else 0.5, edgecolor=BG, linewidth=0.6, zorder=2)
    if is_repeat:
        sim = call["sims"][profile]
        ax1.annotate(f"actor recognized: {sim:.0%} match to actor {profile[-1].upper()}",
                     xy=(start, y), xytext=(start + 2, y + 0.36),
                     fontsize=9, color=HIGHLIGHT, fontweight="bold",
                     arrowprops=dict(arrowstyle="-", color=HIGHLIGHT, lw=0.9))
        ax1.scatter(call["duration"] + 3, y, marker="*", s=150, color=HIGHLIGHT,
                    edgecolor=BG, linewidth=0.5, zorder=4)
    else:
        ax1.text(call["duration"] - 2, y, "new actor", ha="right", va="center",
                 fontsize=8.4, color=MUTED)
    ax1.text(-4, y, call["id"], ha="right", va="center", fontsize=9,
             color=FG, fontfamily="monospace")

ax1.set_xlim(-14, 108)
ax1.set_xlabel("seconds into the interaction (bars = caller's speech, the audio used to ID them)",
               color=MUTED, fontsize=9)
ax1.set_title("The core capability: one actor, three interactions, recognized by voice alone",
              fontsize=13, fontweight="bold", color=FG, loc="left", pad=10)
ax1.set_yticks([])
ax1.tick_params(colors=MUTED, labelsize=8)
for spine in ax1.spines.values():
    spine.set_color(GRID)
ax1.text(106, 5.44, "filled bars = recognized repeat actor (★)", ha="right",
         va="center", fontsize=8.4, color=MUTED)

# ------------------------------------------------------------ Panel 2: decision bar
ax2 = fig.add_subplot(gs[1])
ax2.set_facecolor(BG)

known = ["voice-profile-a", "voice-profile-b", "voice-profile-c"]
width = 0.22
for j, profile in enumerate(known):
    for i, call in enumerate(CALLS):
        value = call["sims"].get(profile)
        if value is None:
            continue
        x = i + (j - 1) * width
        ax2.bar(x, value, width=width, color=PROFILE_COLORS[profile],
                alpha=0.8, edgecolor=BG, zorder=2)

ax2.axhline(THRESHOLD, color="#b8860b", linestyle="--", linewidth=1.5, zorder=3)
ax2.text(0.02, THRESHOLD - 0.032, "confidence bar 0.80 — match claimed only above",
         color="#b8860b", fontsize=8.6, ha="left", fontweight="bold")

for call_index, call in enumerate(CALLS):
    if call["match"][0] == "re-id":
        sim = call["sims"][call["match"][1]]
        ax2.annotate(f"{sim:.0%} → recognized",
                     xy=(call_index, sim), xytext=(call_index, sim + 0.10),
                     fontsize=9, color=HIGHLIGHT, fontweight="bold", ha="center",
                     arrowprops=dict(arrowstyle="->", color=HIGHLIGHT, lw=1.1))

ax2.set_xticks(range(len(CALLS)))
ax2.set_xticklabels([call["id"] for call in CALLS], fontsize=8, color=MUTED, rotation=20)
ax2.set_ylim(0, 1.22)
ax2.set_ylabel("similarity of this call's voice to each past actor", color=MUTED, fontsize=9)
ax2.set_title("Reliability: we only flag someone as a repeat actor when confidence clears the bar",
              fontsize=13, fontweight="bold", color=FG, loc="left", pad=10)
ax2.legend([plt.Rectangle((0, 0), 1, 1, fc=c) for c in PROFILE_COLORS.values()],
           ["actor A", "actor B", "actor C"], frameon=False, fontsize=8.5,
           labelcolor=FG, loc="upper left")
ax2.tick_params(colors=MUTED, labelsize=8)
ax2.grid(axis="y", color=GRID, linewidth=0.8)
ax2.set_axisbelow(True)
for spine in ax2.spines.values():
    spine.set_color(GRID)

# ----------------------------------------------------------- Panel 3: value accrual
ax3 = fig.add_subplot(gs[2])
ax3.set_facecolor(BG)

cumulative = 0
cum_values = []
attempted = [call["attempted"] for call in CALLS]
for amount in attempted:
    cumulative += amount
    cum_values.append(cumulative)

bars = ax3.bar(range(len(CALLS)), attempted, color="#dfe6ef", edgecolor=BG,
               zorder=2, label="transfer amount attempted in that call")
for i, amount in enumerate(attempted):
    if amount > 0:
        bars[i].set_color(ACCENT)
        bars[i].set_alpha(0.85)
        ax3.text(i, amount / 2, f"${amount:,}", ha="center", va="center",
                 fontsize=8.6, color="white", fontweight="bold")

ax3.plot(range(len(CALLS)), cum_values, color="#1d2733", linewidth=2.2,
         marker="o", markersize=6, zorder=4, label="cumulative losses averted")
for i, value in enumerate(cum_values):
    ax3.annotate(f"${value:,}", (i, value), textcoords="offset points",
                 xytext=(0, 11), fontsize=8.4, color=FG, fontweight="bold",
                 fontfamily="monospace", ha="center")

ax3.annotate(
    "$4,000 of the total was only stoppable because the system\n"
    "remembered the actor from earlier calls. A single-call check\n"
    "would not know this was the same scammer.",
    xy=(4, 6000), xytext=(0.6, 7300), fontsize=8.6, color=MUTED,
    arrowprops=dict(arrowstyle="->", color=MUTED, lw=1),
)

ax3.set_xticks(range(len(CALLS)))
ax3.set_xticklabels([call["id"] for call in CALLS], fontsize=8, color=MUTED, rotation=20)
ax3.set_ylim(0, 9500)
ax3.set_ylabel("US dollars", color=MUTED, fontsize=9)
ax3.set_title("Value story: memory compounds — each new interaction makes the next one cheaper to stop",
              fontsize=13, fontweight="bold", color=FG, loc="left", pad=10)
ax3.legend(frameon=False, fontsize=8.5, labelcolor=FG, loc="upper left")
ax3.tick_params(colors=MUTED, labelsize=8)
ax3.grid(axis="y", color=GRID, linewidth=0.8)
ax3.set_axisbelow(True)
for spine in ax3.spines.values():
    spine.set_color(GRID)

fig.text(0.07, 0.015,
         "Illustrative scenario for product discussion — figures intentionally simplified.",
         fontsize=8, color=MUTED)

fig.savefig("reid-vc-visualization.png", dpi=150, facecolor=BG, bbox_inches="tight",
            transparent=True)
print("saved reid-vc-visualization.png")