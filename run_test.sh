#!/bin/bash
# =============================================================================
# run_test.sh — Automated QoS Test Runner
# Tugas Akhir: Implementasi QoS untuk Trafik Real-Time pada Jaringan SDN
# Muhammad Fithriyanto — Teknik Telekomunikasi ITS
# =============================================================================
# Usage:
#   bash run_test.sh [beban_mbps] [mode]
#   beban_mbps : 2 | 4 | 6 | 8  (default: semua)
#   mode       : off | on | both  (default: both)
#
# Example:
#   bash run_test.sh 4 both    # uji beban 4 Mbps, QoS off dan on
#   bash run_test.sh           # uji semua beban
# =============================================================================

set -e

# ---------- Konfigurasi ----------
H_SENDER="h1"
H_RECV="h4"
H_BG_SEND="h2"
H_BG_RECV="h5"

IP_RECV="10.0.0.4"
IP_BG_RECV="10.0.0.5"

VOIP_PORT=5001
BG_PORT=5201
DURATION=60000        # ms (60 detik)
N_RUNS=5

RESULTS_DIR="results"
mkdir -p "$RESULTS_DIR"

LOADS=(2 4 6 8)       # Mbps
LOAD_ARG=$1
MODE_ARG=${2:-both}

if [ -n "$LOAD_ARG" ]; then
    LOADS=("$LOAD_ARG")
fi

# ---------- Fungsi ----------
log() { echo "[$(date '+%H:%M:%S')] $*"; }

run_single() {
    local load=$1      # Mbps
    local qos_mode=$2  # off | on
    local run_num=$3

    local bitrate=$((load * 1000000))
    local tag="load${load}mbps_qos${qos_mode}_run${run_num}"
    local log_recv="${RESULTS_DIR}/${tag}_recv.log"
    local log_send="${RESULTS_DIR}/${tag}_send.log"

    log "=== Run $run_num | Beban ${load} Mbps | QoS ${qos_mode} ==="

    # Terapkan / lepas QoS
    if [ "$qos_mode" = "on" ]; then
        log "Mengaktifkan HTB QoS..."
        sudo bash setup_qos.sh > /dev/null 2>&1
    else
        log "Menonaktifkan QoS (FIFO)..."
        sudo ovs-vsctl clear port s1-eth1 qos 2>/dev/null || true
        sudo ovs-vsctl clear port s1-eth2 qos 2>/dev/null || true
    fi

    sleep 1

    # Jalankan di Mininet CLI via expect / mnexec
    # Receiver VoIP
    sudo mnexec -a "$(pgrep -f 'mininet:h4')" \
        ITGRecv -l "$log_recv" &
    RECV_PID=$!
    sleep 0.5

    # Background TCP (iperf3)
    sudo mnexec -a "$(pgrep -f 'mininet:h5')" \
        iperf3 -s -p $BG_PORT -D --logfile /dev/null
    sudo mnexec -a "$(pgrep -f 'mininet:h2')" \
        iperf3 -c $IP_BG_RECV -p $BG_PORT -t $((DURATION/1000)) \
        --logfile "${RESULTS_DIR}/${tag}_bg.log" &
    BG_PID=$!

    # VoIP sender (D-ITG)
    sudo mnexec -a "$(pgrep -f 'mininet:h1')" \
        ITGSend \
            -a "$IP_RECV" \
            -T UDP \
            -rp $VOIP_PORT \
            -b "$bitrate" \
            -t "$DURATION" \
            -l "$log_send" \
            -x "$log_recv"

    # Tunggu background selesai
    wait $BG_PID 2>/dev/null || true
    kill $RECV_PID 2>/dev/null || true

    log "Run $run_num selesai. Log: $log_recv"
    sleep 2
}

decode_results() {
    log "Mendekode log D-ITG..."
    for log_file in "${RESULTS_DIR}"/*_recv.log; do
        out="${log_file/_recv.log/_decoded.txt}"
        ITGDec "$log_file" > "$out" 2>/dev/null && \
            log "Decoded: $(basename $out)" || \
            log "Gagal decode: $(basename $log_file)"
    done
}

# ---------- Main ----------
log "=== Memulai pengujian QoS ==="
log "Beban: ${LOADS[*]} Mbps | Mode: $MODE_ARG | Repetisi: $N_RUNS"

for load in "${LOADS[@]}"; do
    if [ "$MODE_ARG" = "off" ] || [ "$MODE_ARG" = "both" ]; then
        for run in $(seq 1 $N_RUNS); do
            run_single "$load" "off" "$run"
        done
    fi

    if [ "$MODE_ARG" = "on" ] || [ "$MODE_ARG" = "both" ]; then
        for run in $(seq 1 $N_RUNS); do
            run_single "$load" "on" "$run"
        done
    fi
done

decode_results

log "=== Semua pengujian selesai ==="
log "Hasil tersimpan di folder: $RESULTS_DIR/"
log "Jalankan: python3 analyze.py $RESULTS_DIR/ untuk analisis"
