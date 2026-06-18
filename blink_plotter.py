import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
import csv
import os
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from matplotlib.ticker import ScalarFormatter
from matplotlib.colors import LinearSegmentedColormap
import argparse
import glob



import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap




def DrawScalingHeatmap(data, fig, ax, sys, collective):
    df = pd.DataFrame(data)

    df = df[
        (df['system'] == sys) &
        (df['collective'] == collective) &
        (df['burst_pause'] == -1) &
        (df['burst_length'] == -1)
    ]
    if df.empty:
        raise ValueError("No data left after filtering")

    df = (df.groupby(['bytes', 'nodes'], as_index=False)
            .agg(avg_speedup=('speedup', 'mean')))

    pivot = df.pivot(index='bytes', columns='nodes', values='avg_speedup')

    # ---------------------------
    # Paper styling (same as DrawLatencyHeatmap)
    # ---------------------------
    sns.set_theme(
        style="ticks",
        context="talk",
        font="DejaVu Sans",
        rc={
            "font.size": 40,
            "axes.titlesize": 50,
            "axes.labelsize": 40,
            "xtick.labelsize": 40,
            "ytick.labelsize": 40,
            "axes.linewidth": 1.2,
            "figure.dpi": 200,
        }
    )

    # ---------------------------
    # Same colormap as DrawLatencyHeatmap
    # ---------------------------
    speedup_cmap = LinearSegmentedColormap.from_list(
        "speedup_red_to_green_to_white",
        [
            (0.00, "#680C17"),
            (0.20, "#B2182B"),
            (0.65, "#FD8B7A"),
            (0.90, "#FDD17A"),
            (0.95, "#B7E4A8"),
            (1.00, "#1A9850"),
        ],
        N=256
    )

    # Clip speedup values > 1.3 to 1.01
    pivot = pivot.applymap(lambda x: 1.01 if x > 1.3 else x)

    hm = sns.heatmap(
        pivot,
        annot=True,
        fmt=".2f",
        cmap=speedup_cmap,
        vmin=0.0, vmax=1.0,
        square=False,
        linewidths=4,
        linecolor="white",
        cbar=False,
        annot_kws={"fontsize": 35},
        ax=ax
    )

    # Titles/labels (match style)
    ax.set_title(f"{collective}", pad=16)
    ax.set_xlabel("Nodes", labelpad=14, fontsize=35)
    ax.set_ylabel("Message Size (bytes)", labelpad=14, fontsize=35)

    # Ticks
    ax.tick_params(axis="both", which="major", length=12, width=2.5)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, ha="center", fontsize=30)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=30)

    # Like the other one: small at top (optional but consistent)
    ax.invert_yaxis()

    # Remove spines
    for spine in ax.spines.values():
        spine.set_visible(False)

    plt.tight_layout()
    return hm


def DrawLatencyHeatmap(data, fig, ax, nodes, sys, collective, msg):
    df = pd.DataFrame(data)

    df = df[
        (df['nodes'] == nodes) &
        (df['system'] == sys) &
        (df['collective'] == collective) &
        (df['bytes'] == msg) &
        (df['burst_pause'] >= 0) &
        (df['burst_length'] >= 0)
    ]
    if df.empty:
        raise ValueError("No data left after filtering")

    df = (df.groupby(['burst_length', 'burst_pause'], as_index=False)
            .agg(avg_speedup=('speedup', 'mean')))

    pivot = df.pivot(index='burst_length', columns='burst_pause', values='avg_speedup')



    pivot = pivot.copy()
    pivot = pivot.applymap(lambda x: 1.01 if x >= 1.1 else x)
    pivot.index = (pd.to_numeric(pivot.index) * 1000).astype(int)
    pivot.columns = (pd.to_numeric(pivot.columns) * 1000)



    # ---------------------------
    # Paper styling (big fonts)
    # ---------------------------
    sns.set_theme(
        style="ticks",           # minimal background
        context="talk",          # larger than "paper"
        font="DejaVu Sans",
        rc={
            # global sizes
            "font.size": 40,
            "axes.titlesize": 50,
            "axes.labelsize": 40,
            "xtick.labelsize": 40,
            "ytick.labelsize": 40,

            # heatmap aesthetics
            "axes.linewidth": 1.2,
            "figure.dpi": 200,
        }
    )

    # ---------------------------
    # Colormap: low=red, ~0.95=green, 1.0=near-white
    # (use slightly off-white so text stays readable)
    # ---------------------------
    speedup_cmap = LinearSegmentedColormap.from_list(
        "speedup_red_to_green_to_white",
        [
            (0.00, "#680C17"),
            (0.20, "#B2182B"),
            (0.65, "#FD8B7A"),
            (0.90, "#FDD17A"),
            (0.95, "#B7E4A8"),
            (1.00, "#1A9850"),
        ],
        N=256
    )

    hm = sns.heatmap(
        pivot,
        annot=True,
        fmt=".2f",
        cmap=speedup_cmap,
        vmin=0.0, vmax=1.0,
        square=True,

        # clean, high-contrast cell grid for papers
        linewidths=4,
        linecolor="white",

        cbar=False,

        # big annotations
        annot_kws={"fontsize": 35},
        ax=ax
    )

    # Titles/labels (bigger + tighter)
    ax.set_title(f"{msg}", pad=16)
    ax.set_xlabel("Burst Pause (ms)", labelpad=14, fontsize=35)
    ax.set_ylabel("Burst Length (ms)", labelpad=14, fontsize=35)

    # Ticks: keep them readable and “paper-ish”
    ax.tick_params(axis="both", which="major", length=12, width=2.5)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, ha="center", fontsize=30)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=30)

    # optional: makes small burst_length appear at top
    ax.invert_yaxis()

    # remove spines (clean)
    for spine in ax.spines.values():
        spine.set_visible(False)

    plt.tight_layout()
    return hm

# -------------------------
# NEW STUFF
# -------------------------

def CleanData(data):
    for key in data.keys():
        data[key] = []
    return data


def to_bytes(size_str):
    size_str = size_str.strip().replace(" ", "").lower()

    i = 0
    while i < len(size_str) and (size_str[i].isdigit() or size_str[i] == '.'):
        i += 1

    number = float(size_str[:i])
    unit = size_str[i:]

    # Binary units (base 1024)
    binary_units = {
        'b': 1,
        'kib': 1024,
        'mib': 1024**2,
        'gib': 1024**3,
    }

    # SI units (base 1000)
    si_units = {
        'kb': 1000,
        'mb': 1000**2,
        'gb': 1000**3,
        'tb': 1000**4,
    }

    if unit in binary_units:
        return int(number * binary_units[unit])
    elif unit in si_units:
        return int(number * si_units[unit])
    else:
        raise ValueError(f"Unknown unit in size string: '{size_str}'")

# Must match the -window (and -grty, if changed) used for the Tournament runs:
# each recorded iteration moves TOURNAMENT_WINDOW messages in each direction.
TOURNAMENT_WINDOW = 64

def ComputeBandwidth(latency, bytes, collective, nodes):

    gbits = (bytes * 8) / 1e9  # Convert bytes to gigabits

    if collective.split(" ")[0] == 'All-to-All':
        total_data = (nodes - 1) * gbits
    elif collective.split(" ")[0] == 'All-Gather':
        total_data = ((nodes-1)/nodes) * gbits
    elif collective.split(" ")[0] == 'Tournament':
        # pairwise full-duplex: a window of messages is exchanged each way
        # per iteration, so the per-pair bidirectional volume is 2*window*msg.
        total_data = 2 * TOURNAMENT_WINDOW * gbits
    else:
        raise ValueError(f"Unknown collective: {collective}")

    bandwidth = total_data / latency
    return bandwidth



def DrawIterationsPlot(data, name):
    print(f"Plotting data collective: {name}")

    # Use a dark theme for the plot
    sns.set_style("whitegrid")  # darker background for axes
    sns.set_context("talk")

    # Create the figure and axes
    f, ax1 = plt.subplots(figsize=(35, 20))

    # Convert input data to a DataFrame
    df = pd.DataFrame(data)
    df['collective_system'] = df['collective'] + "_" + df['system']

    # Plot with seaborn
    fig = sns.scatterplot(
        data=df,
        x='iteration',
        y='latency',
        hue='collective_system',
        s=200,
        ax=ax1,
        alpha=0.9
    )

    # ax1.axhline(
    #     y=200,
    #     color='red',
    #     linestyle='--',
    #     linewidth=6,
    #     label=f'Nanjing Theoretical Peak {200} Gb/s'
    # )

    # ax1.axhline(
    #     y=100,
    #     color='red',
    #     linestyle=':',
    #     linewidth=6,
    #     label=f'HAICGU Theoretical Peak {100} Gb/s'
    # )

    # Labeling and formatting
    ax1.set_xlim(0, len(df["iteration"].unique()) - 1)
    ax1.tick_params(axis='both', which='major', labelsize=45)
    ax1.set_ylabel('Bandwidth (Gb/s)', fontsize=45, labelpad=20)
    ax1.set_xlabel('Iterations', fontsize=45, labelpad=20)
    #ax1.set_title(f'{name}', fontsize=45, pad=30)

    # Show legend and layout
    # Filtra legenda: solo cluster_collective unici + linea teorica

    ax1.legend(
        fontsize=45,           # grandezza testo etichette
        loc='upper center',
        bbox_to_anchor=(0.5, -0.2),  # più spazio sotto
        ncol=2,
        frameon=True,
        title=None,
        markerscale=2.0        # ingrandisce i marker nella legenda
    )
    plt.tight_layout()

    # Save the figure
    plt.savefig(f'plots/{name}_scatter.png', dpi=300)  # save with dark background

def DrawLatencyViolinPlot(data, name):
    print(f"Plotting violin plot: {name}")

    # Style
    sns.set_style("whitegrid")
    sns.set_context("talk")

    # Figure
    f, ax = plt.subplots(figsize=(40, 30))

    # DataFrame
    df = pd.DataFrame(data)
    df['collective_system'] = df['collective'] + "_" + df['system']

    palette_base = ["#4C72B0", "#55A868", "#C44E52"]

    # Build a palette where each color repeats for 3 categories
    unique_x = df["collective_system"].unique()
    palette = [palette_base[i // 3 % len(palette_base)] for i in range(len(unique_x))]

    sns.boxplot(
        data=df,
        x='collective_system',
        y='latency',
        ax=ax,
        showfliers=False,
        palette=palette
    )

    # Labels
    ax.set_xlabel("Collective", fontsize=40, labelpad=23)
    ax.set_ylabel("Latency (s)", fontsize=40, labelpad=23)
    ax.tick_params(axis='x', rotation=90, labelsize=32)
    ax.tick_params(axis='y', labelsize=40)
    # Save
    plt.tight_layout()
    plt.savefig(f"plots/{name}_violin.png", dpi=300, bbox_inches="tight")
    plt.close()


def DrawBandwidthPlot(data, name, nodes, sys):
    print(f"Plotting data collective: {name}")

    # Imposta stile e contesto
    sns.set_style("whitegrid")
    sns.set_context("talk")

    # Crea figura principale
    f, ax1 = plt.subplots(figsize=(30, 15))

    # Conversione e filtra dati in DataFrame
    df = pd.DataFrame(data)
    df = df[df['nodes'] == nodes]
    df = df[df['system'] == sys]
    df['collective_system'] = df['collective'] + "_" + df['system']

    # --- Lineplot principale ---
    sns.lineplot(
        data=df,
        x='message',
        y='bandwidth',
        hue='collective_system',
        style='collective_system',
        markers=True,
        markersize=10,
        linewidth=8,
        ax=ax1
    )

    # Linea teorica
    ax1.axhline(
        y=200,
        color='red',
        linestyle=':',
        linewidth=5,
        label=f'Theoretical Peak {200} Gb/s'
    )

    # Etichette
    ax1.set_xlim(0, len(df["message"].unique()) - 1)
    ax1.tick_params(axis='both', which='major', labelsize=40)
    ax1.set_ylabel('Bandwidth (Gb/s)', fontsize=40, labelpad=23)
    ax1.set_xlabel('Message Size', fontsize=40, labelpad=23)
    #ax1.set_title(f'{name}', fontsize=38, pad=30)

    # Legenda centrata in basso
    ax1.legend(
        fontsize=40,
        loc='upper center',
        bbox_to_anchor=(0.5, -0.2),
        ncol=2,
        frameon=True,
        title=None,
    )

    # --- Subplot zoom-in --- ["agtr", "agtr_con
    zoom_msgs = ['8', '64', '512', '4096']
    df_zoom = df[df['message'].isin(zoom_msgs)]
    #! This line creates a warning
    df_zoom['latency_scaled'] = df_zoom['latency'] * 1e6

    axins = inset_axes(ax1, width="43%", height="43%", loc='upper left', borderpad=7)
    sns.lineplot(
        data=df_zoom,
        x='message',
        y='latency_scaled',
        hue='collective_system',
        style='collective_system',
        markers=True,
        markersize=8,
        linewidth=7,
        ax=axins,
        legend=False  # no legend in zoom
    )

    # Optional: adjust ticks for zoom clarity
    #axins.set_ylim(1, 10)
    axins.set_xlim(0, len(df_zoom["message"].unique()) - 1)
    axins.tick_params(axis='both', which='major', labelsize=28)
    axins.set_title("")
    axins.set_xlabel('', fontsize=28, labelpad=23)
    axins.set_ylabel('Latency (us)', fontsize=28, labelpad=23)

    # --- Layout e salvataggio ---
    plt.savefig(f'plots/{name}_line.png', dpi=300, bbox_inches='tight')
    plt.close()




def LoadData_LUMI_ONLY(data, data_folder, systems, collectives, messages, nodes):

    with open(data_folder, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            path = row["path"]
            system = row["system"]
            collective = row["extra"]
            data_nodes = row["numnodes"]


            data_path = os.path.join(path, f"data_app_0.csv")
            if not os.path.exists(data_path):
                continue


            if (int(data_nodes) not in nodes):
                continue
            
            if (system not in systems):
                continue
            
            if (collective not in collectives):
                continue

            #forse è qui il problema

            nodes_for_bw = int(data_nodes) / 2
            # print(f"Processing path: {path}, system: {system}, collective: {collective}, nodes: {data_nodes}")

            collective_string = collective.strip().split(" ")
            if len(collective_string) == 1:
                collective_name = collective_string[0]
            elif len(collective_string) > 1:
                collective_name = collective_string[0]+" "+collective_string[1]
            
            if len(collective_string) > 2:
                burst_pause = float(collective_string[2])
                burst_length = float(collective_string[3])


            for i in range(8):
                i_base = i
                i_cong = i + 8

                base_sum = 0.0
                base_rows = 0
                cong_sum = 0.0
                cong_rows = 0

                base_path = os.path.join(path, f"data_app_{i_base}.csv")
                cong_path = os.path.join(path, f"data_app_{i_cong}.csv")

                # --- baseline ---
                with open(base_path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row_counter, row in enumerate(reader):
                        m_bytes = int(row["msg_size"])
                        if m_bytes not in messages:
                            continue   # <-- important

                        latency = float(row[f"{i_base}_Max-Duration_s"])
                        base_sum += latency
                        base_rows += 1
                        bandwidth = ComputeBandwidth(latency, m_bytes, collective_name, nodes_for_bw)
                        data['latency'].append(latency)
                        data['bandwidth'].append(bandwidth)
                        data['message'].append(str(m_bytes))
                        data['collective'].append(collective_name)
                        data['bytes'].append(m_bytes)
                        data['system'].append(system)
                        data['iteration'].append(row_counter)
                        data['nodes'].append(int(data_nodes))
                        data['burst_length'].append(burst_length if 'burst_length' in locals() else -1)
                        data['burst_pause'].append(burst_pause if 'burst_pause' in locals() else -1)


                if base_rows == 0:
                    continue

                lat_baseline = base_sum / base_rows
                data['avg_latency'].extend([lat_baseline] * base_rows)
                data['speedup'].extend([1.0] * base_rows)

                # --- congested ---
                with open(cong_path, newline="") as f:
                    reader = csv.DictReader(f)
                    for row_counter, row in enumerate(reader):
                        m_bytes = int(row["msg_size"])
                        if m_bytes not in messages:
                            continue   # <-- important

                        latency = float(row[f"{i_cong}_Max-Duration_s"])
                        cong_sum += latency
                        cong_rows += 1
                        bandwidth = ComputeBandwidth(latency, m_bytes, collective_name, nodes_for_bw)
                        data['latency'].append(latency)
                        data['bandwidth'].append(bandwidth)
                        data['message'].append(str(m_bytes))
                        data['collective'].append(collective_name)
                        data['bytes'].append(m_bytes)
                        data['system'].append(system)
                        data['iteration'].append(row_counter)
                        data['nodes'].append(int(data_nodes))
                        data['burst_length'].append(burst_length if 'burst_length' in locals() else -1)
                        data['burst_pause'].append(burst_pause if 'burst_pause' in locals() else -1)


                if cong_rows == 0:
                    continue

                lat_cong = cong_sum / cong_rows
                data['avg_latency'].extend([lat_cong] * cong_rows)
                data['speedup'].extend([lat_baseline / lat_cong] * cong_rows)


def LoadData(data, data_folder, systems, collectives, messages, nodes):

    with open(data_folder, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            path = row["path"]
            system = row["system"]
            collective = row["extra"]
            data_nodes = row["numnodes"]

            data_path = os.path.join(path, f"data_app_0.csv")
            if not os.path.exists(data_path):
                continue

            if (int(data_nodes) not in nodes):
                continue
            
            if (system not in systems):
                continue
            
            if (collective not in collectives):
                continue

            #forse è qui il problema

            nodes_for_bw = int(data_nodes) / 2
            print(f"Processing path: {path}, system: {system}, collective: {collective}, nodes: {data_nodes}")

            collective_string = collective.strip().split(" ")
            if len(collective_string) == 1:
                collective_name = collective_string[0]
            elif len(collective_string) > 1:
                collective_name = collective_string[0]+" "+collective_string[1]
            
            if len(collective_string) > 2:
                burst_pause = float(collective_string[2])
                burst_length = float(collective_string[3])

            csv_files = sorted(glob.glob(os.path.join(path, "data_app_*.csv")))
            for i in range(len(csv_files)):

                # print("Accessing:", csv_files[i])
                avg_lat = 0
                skip = False
                with open(csv_files[i], newline="") as f:
                    reader = csv.DictReader(f)
                    row_counter = 0
                    for row in reader:
                        latency = float(row[f"{i}_Max-Duration_s"])
                        m_bytes = int(row["msg_size"])

                        if m_bytes not in messages:
                            skip = True
                            break

                        avg_lat += latency
                        bandwidth = ComputeBandwidth(latency, m_bytes, collective_name, nodes_for_bw)
                        data['latency'].append(latency)
                        data['bandwidth'].append(bandwidth)
                        data['message'].append(str(m_bytes))
                        data['collective'].append(collective_name)
                        data['bytes'].append(m_bytes)
                        data['system'].append(system)
                        data['iteration'].append(row_counter)
                        data['nodes'].append(int(data_nodes))
                        data['burst_length'].append(burst_length if 'burst_length' in locals() else -1)
                        data['burst_pause'].append(burst_pause if 'burst_pause' in locals() else -1)
                        data['speedup'].append(-1)
                        row_counter += 1
                if not skip:
                    data['avg_latency'].extend([avg_lat/row_counter] * row_counter)
        

def SpeedupSCALE(data, collective):
    df = pd.DataFrame(data)
    print("Speedup starting")

    df_baseline = df[
        (df['collective'] == collective.split(" ")[0]) &
        (df['burst_pause'] == -1) &
        (df['burst_length'] == -1)
    ]

    df_baseline = (
        df_baseline
        .groupby(['nodes', 'collective', 'system', 'bytes'], as_index=False)
        .agg(max_latency=('avg_latency', 'max'))
    )

    for i in range(len(data["collective"])):
        
        df_aux = df_baseline[
            (df_baseline['nodes'] == data["nodes"][i]) &
            (df_baseline['bytes'] == data["bytes"][i])
        ]
        baseline = df_aux["max_latency"].iloc[0]
        data["speedup"][i] = baseline/data["avg_latency"][i] 


    df = pd.DataFrame(data)
    df = (
        df
        .groupby(['nodes', 'collective', 'system', 'bytes'], as_index=False)
        .agg(avg_speedup=('speedup', 'mean'))
    )
    df.to_csv('plots/speedup_results.csv', index=False)

def SpeedupLAT(data, collective):
    df = pd.DataFrame(data)
    print("Speedup starting")
    
    df_baseline = df[
        (df['collective'] == collective.split(" ")[0]) #&
        # (df['burst_pause'] == -1) &
        # (df['burst_length'] == -1)
    ]
    
    df_baseline = (
        df_baseline
        .groupby(['nodes', 'collective', 'system', 'bytes', 'burst_length', 'burst_pause'], as_index=False)
        .agg(max_latency=('avg_latency', 'max'))
    )
    baseline = df_baseline["max_latency"].iloc[0]
    for i in range(len(data["collective"])):
        data["speedup"][i] = baseline/data["avg_latency"][i] 
    df_baseline.to_csv('plots/speedup_results.csv', index=False)
    df = pd.DataFrame(data)

if __name__ == "__main__":

    data_folder = f"data/description.csv"
    data = {
        'message': [],
        'bytes': [],
        'latency': [],
        'bandwidth': [],
        'system': [],
        'collective': [],
        'iteration': [],
        'nodes': [],
        'burst_length': [],
        'burst_pause': [],
        'avg_latency': [],
        'speedup':[]
    }


    collectives_sustained = ['All-to-All', 'All-to-All A2A-Congested', 'All-to-All Inc-Congested',
                             'All-Gather', 'All-Gather A2A-Congested', 'All-Gather Inc-Congested']
    collectives_sustained_a2a = ['All-Gather A2A-Congested', 'All-Gather Inc-Congested','All-Gather']
    collectives_bursty = ['All-to-All Inc-Congested 0.01 0.1', 'All-to-All Inc-Congested 0.01 0.01', 'All-to-All Inc-Congested 0.01 0.001',
                          'All-to-All A2A-Congested 0.01 0.1', 'All-to-All A2A-Congested 0.01 0.01', 'All-to-All A2A-Congested 0.01 0.001',
                          'All-to-All Inc-Congested 0.0001 0.1', 'All-to-All Inc-Congested 0.0001 0.01', 'All-to-All Inc-Congested 0.0001 0.001',
                          'All-to-All A2A-Congested 0.0001 0.1', 'All-to-All A2A-Congested 0.0001 0.01', 'All-to-All A2A-Congested 0.0001 0.001',
                          'All-to-All Inc-Congested 0.000001 0.1', 'All-to-All Inc-Congested 0.000001 0.01', 'All-to-All Inc-Congested 0.000001 0.001',
                          'All-to-All A2A-Congested 0.000001 0.1', 'All-to-All A2A-Congested 0.000001 0.01', 'All-to-All A2A-Congested 0.000001 0.001',
                          'All-Gather Inc-Congested 0.01 0.1', 'All-Gather Inc-Congested 0.01 0.01', 'All-Gather Inc-Congested 0.01 0.001',
                          'All-Gather A2A-Congested 0.01 0.1', 'All-Gather A2A-Congested 0.01 0.01', 'All-Gather A2A-Congested 0.01 0.001',
                          'All-Gather Inc-Congested 0.0001 0.1', 'All-Gather Inc-Congested 0.0001 0.01', 'All-Gather Inc-Congested 0.0001 0.001',
                          'All-Gather A2A-Congested 0.0001 0.1', 'All-Gather A2A-Congested 0.0001 0.01', 'All-Gather A2A-Congested 0.0001 0.001',
                          'All-Gather Inc-Congested 0.000001 0.1', 'All-Gather Inc-Congested 0.000001 0.01', 'All-Gather Inc-Congested 0.000001 0.001',
                          'All-Gather A2A-Congested 0.000001 0.1', 'All-Gather A2A-Congested 0.000001 0.01', 'All-Gather A2A-Congested 0.000001 0.001',
                          'All-to-All', 'All-Gather']

    collectives_bursty_lumi = ['All-to-All Inc-Congested 0.01 0.1', 'All-to-All Inc-Congested 0.01 0.01', 'All-to-All Inc-Congested 0.01 0.001',
                            'All-to-All A2A-Congested 0.01 0.1', 'All-to-All A2A-Congested 0.01 0.01', 'All-to-All A2A-Congested 0.01 0.001',
                            'All-to-All Inc-Congested 0.0001 0.1', 'All-to-All Inc-Congested 0.0001 0.01', 'All-to-All Inc-Congested 0.0001 0.001',
                            'All-to-All A2A-Congested 0.0001 0.1', 'All-to-All A2A-Congested 0.0001 0.01', 'All-to-All A2A-Congested 0.0001 0.001',
                            'All-to-All Inc-Congested 0.000001 0.1', 'All-to-All Inc-Congested 0.000001 0.01', 'All-to-All Inc-Congested 0.000001 0.001',
                            'All-to-All A2A-Congested 0.000001 0.1', 'All-to-All A2A-Congested 0.000001 0.01', 'All-to-All A2A-Congested 0.000001 0.001',
                            'All-Gather Inc-Congested 0.01 0.1', 'All-Gather Inc-Congested 0.01 0.01', 'All-Gather Inc-Congested 0.01 0.001',
                            'All-Gather A2A-Congested 0.01 0.1', 'All-Gather A2A-Congested 0.01 0.01', 'All-Gather A2A-Congested 0.01 0.001',
                            'All-Gather Inc-Congested 0.0001 0.1', 'All-Gather Inc-Congested 0.0001 0.01', 'All-Gather Inc-Congested 0.0001 0.001',
                            'All-Gather A2A-Congested 0.0001 0.1', 'All-Gather A2A-Congested 0.0001 0.01', 'All-Gather A2A-Congested 0.0001 0.001',
                            'All-Gather Inc-Congested 0.000001 0.1', 'All-Gather Inc-Congested 0.000001 0.01', 'All-Gather Inc-Congested 0.000001 0.001',
                            'All-Gather A2A-Congested 0.000001 0.1', 'All-Gather A2A-Congested 0.000001 0.01', 'All-Gather A2A-Congested 0.000001 0.001']

    messages = ['8B', '64B', '512B', '4KiB', '32KiB', '256KiB', '2MiB', '16MiB'] # ,'128MiB']
    for i in range(len(messages)):
        messages[i] = to_bytes(messages[i])
 

    leonardo = {
        "name": "leonardo",
        "partition": "boost_usr_prod",
        "account": "IscrB_SWING",
        "path": "/leonardo/home/userexternal/lpiarull/CRAB/wrappers/",
        "sus_nodes": [8, 16, 32, 64, 128],
        "bur_nodes": [128]
    }

    lumi = {
        "name": "lumi",
        "partition": "standard-g",
        "account": "project_465001736",
        "path": "/users/pasqualo/CRAB/wrappers/",
        "sus_nodes": [8, 16, 32, 64, 128, 256],
        "bur_nodes": [64, 256]
    }

    cresco8 = {
        "name": "cresco8",
        "partition": "cresco8_cpu",
        "account": "ssheneaadm",
        "path": "/afs/enea.it/fra/user/faltelli/CRAB/wrappers/",
        "sus_nodes": [8, 16, 32, 64, 128, 256],
        "bur_nodes": [64, 128]
    }

    systems=[leonardo] #lumi, leonardo  cresco8, 

    # # BASIC BANDWIDTH
    # for sys in systems:
    #     for nodes in node_list:
    #         DrawBandwidthPlot(data, f"PLOT_BW_{sys}_sustained_{nodes}", nodes, sys)
    
    #HEATMAPS SPEEDUP
    for sys in systems:
        sys_name = sys["name"]
        for nodes in sys["bur_nodes"]:
            for collective in collectives_sustained:
                done = True
                heatmaps = []
                fig, axes = plt.subplots(1, len(messages), figsize=(9 * len(messages), 8), sharex=True)
                for ax, msg in zip(axes, messages):
                    if "Congested" not in collective:
                        done = False
                        continue

                    print(f"sys: {sys_name} nodes: {nodes} collective: {collective} msg: {msg}")

                    # if sys == lumi:
                    #     LoadData_LUMI_ONLY(data, lumi_data_folder, [sys_name], collectives_bursty_lumi, [msg], [nodes])
                    # else:
                    LoadData(data, data_folder, [sys_name], collectives_bursty, [msg], [nodes])
                    SpeedupLAT(data, collective)
                   
                    hm=DrawLatencyHeatmap(data, fig, ax, nodes, sys_name, collective, msg)              
                    CleanData(data)
                    heatmaps.append(hm)
                if done:
                    cbar_ax = fig.add_axes([0.123, 1.15, 0.78, 0.03])  # [left, bottom, width, height]
                    fig.colorbar(heatmaps[0].collections[0], cax=cbar_ax, orientation="horizontal")
                    cbar_ax.tick_params(labelsize=40)  
                    plt.savefig(f"plots/PLOT_HEATMAPS_{sys_name}_{collective}_{nodes}_{msg}", dpi=300, bbox_inches='tight')
                    plt.close()

                
    # colls = collectives_sustained_a2a.copy()
    # colls.pop()
    # # # HEATMAP SCALING
    # for sys in systems:
    #     sys_name = sys["name"]
    #     heatmaps = []
    #     fig, axes = plt.subplots(2, 1, figsize=(20 , 8 * 2), sharex=True)
    #     for collective, ax in zip(colls, axes):
    #         print(f"sys: {sys_name} collective: {collective}")
    #         LoadData(data, data_folder, [sys_name], collectives_sustained_a2a, messages, sys["sus_nodes"])
    #         SpeedupSCALE(data, collective)
    #         hm=DrawScalingHeatmap(data, fig, ax, sys_name, collective)              
    #         CleanData(data)
    #         heatmaps.append(hm)

    #     cbar_ax = fig.add_axes([0.123, 1.15, 0.78, 0.03])  # [left, bottom, width, height]
    #     fig.colorbar(heatmaps[0].collections[0], cax=cbar_ax, orientation="horizontal")
    #     cbar_ax.tick_params(labelsize=40)  
    #     plt.savefig(f"plots/SCALING_{sys_name}_{collective}", dpi=300, bbox_inches='tight')
    #     plt.close()
    

