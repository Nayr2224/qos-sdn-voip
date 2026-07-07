#!/bin/bash
LINK_BW_BPS=10000000
Q0_MIN=7000000
Q0_MAX=10000000
Q1_MIN=1000000
Q1_MAX=10000000
BOTTLENECK_PORTS=("s1-eth1" "s1-eth2")

echo "[*] Membersihkan QoS lama..."
for PORT in "${BOTTLENECK_PORTS[@]}"; do
    ovs-vsctl clear port "$PORT" qos 2>/dev/null || true
done
ovs-vsctl --all destroy qos 2>/dev/null || true
ovs-vsctl --all destroy queue 2>/dev/null || true

for PORT in "${BOTTLENECK_PORTS[@]}"; do
    echo "[*] Setup HTB di $PORT"
    ovs-vsctl set port "$PORT" qos=@newqos -- \
        --id=@newqos create qos type=linux-htb \
            other-config:max-rate=$LINK_BW_BPS \
            queues:0=@q0 \
            queues:1=@q1 -- \
        --id=@q0 create queue \
            other-config:min-rate=$Q0_MIN \
            other-config:max-rate=$Q0_MAX \
            other-config:priority=100 -- \
        --id=@q1 create queue \
            other-config:min-rate=$Q1_MIN \
            other-config:max-rate=$Q1_MAX \
            other-config:priority=10
    echo "[✓] Done $PORT"
done

echo ""
echo "[✓] QoS berhasil! Verifikasi:"
ovs-vsctl list qos
