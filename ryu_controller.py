from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (CONFIG_DISPATCHER, MAIN_DISPATCHER,
                                     DEAD_DISPATCHER, set_ev_cls)
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4, udp, tcp, ether_types
from ryu.lib import hub

# ── Konfigurasi QoS ──────────────────────────────────────────────────────────
REALTIME_UDP_PORTS = {5001, 5003}   # port VoIP / video (iperf3 UDP)
QUEUE_REALTIME     = 0              # HTB queue 0 — prioritas tinggi
QUEUE_BACKGROUND   = 1              # HTB queue 1 — best effort

# ── Konfigurasi monitor kongesti ─────────────────────────────────────────────
MONITOR_PORT        = 2             # port bottleneck yang dipantau (s1-eth1/eth2)
MONITOR_INTERVAL    = 5             # detik
SPIKE_FACTOR        = 1.5           # kalau naik 1.5x dari sebelumnya = kongesti
MIN_SPIKE_MBPS      = 5             # threshold minimum agar tidak false alarm


class QosController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QosController, self).__init__(*args, **kwargs)
        self.mac_to_port  = {}    # {dpid: {mac: port}}
        self.datapaths    = {}    # {dpid: datapath}
        self.prev_tx      = {}    # untuk hitung throughput
        self.prev_rate    = {}    # untuk deteksi spike
        # Jalankan thread monitor di background
        self.monitor_thread = hub.spawn(self._monitor)

    # =========================================================================
    # BAGIAN 1 — SETUP SWITCH (WAJIB ADA, ini yang hilang di kode aslimu)
    # =========================================================================

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Dipanggil saat switch baru konek ke controller.
        Pasang table-miss rule supaya paket yang belum dikenal
        dikirim ke controller dulu.
        Tanpa ini: pingall PASTI gagal.
        """
        dp      = ev.msg.datapath
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        dpid    = dp.id

        self.logger.info("✅ Switch s%s terkoneksi", dpid)
        self.mac_to_port.setdefault(dpid, {})

        # Table-miss: paket tak dikenal → kirim ke controller
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._install_flow(dp, priority=0, match=match, actions=actions)

    # =========================================================================
    # BAGIAN 2 — FORWARDING + QoS (inti QoS ada di sini)
    # =========================================================================

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg      = ev.msg
        dp       = msg.datapath
        ofproto  = dp.ofproto
        parser   = dp.ofproto_parser
        dpid     = dp.id
        in_port  = msg.match['in_port']

        pkt     = packet.Packet(msg.data)
        eth     = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        # Pelajari MAC address
        self.mac_to_port[dpid][eth.src] = in_port
        out_port = (self.mac_to_port[dpid].get(eth.dst)
                    or ofproto.OFPP_FLOOD)

        # ── Tentukan queue berdasarkan jenis traffic ───────────────────────
        ip  = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)
        tcp_pkt = pkt.get_protocol(tcp.tcp)

        queue_id = QUEUE_BACKGROUND   # default: background

        if ip and udp_pkt:
            if (udp_pkt.dst_port in REALTIME_UDP_PORTS or
                    udp_pkt.src_port in REALTIME_UDP_PORTS):
                queue_id = QUEUE_REALTIME

        # ── Buat actions dengan set_queue ──────────────────────────────────
        if out_port != ofproto.OFPP_FLOOD:
            actions = [
                parser.OFPActionSetQueue(queue_id),
                parser.OFPActionOutput(out_port)
            ]

            # Install flow rule agar paket berikutnya tidak perlu ke controller
            if ip and udp_pkt and queue_id == QUEUE_REALTIME:
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_type=ether_types.ETH_TYPE_IP,
                    ip_proto=17,
                    udp_dst=udp_pkt.dst_port
                )
                self._install_flow(dp, priority=200, match=match, actions=actions)
                self.logger.info("🎯 [S%s] Flow REALTIME UDP:%s → queue %d → port %d",
                                 dpid, udp_pkt.dst_port, queue_id, out_port)

            elif ip and tcp_pkt:
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=eth.dst,
                    eth_type=ether_types.ETH_TYPE_IP,
                    ip_proto=6
                )
                self._install_flow(dp, priority=100, match=match, actions=actions)

            else:
                match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
                self._install_flow(dp, priority=1, match=match, actions=actions)

        else:
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]

        # Kirim paket pertama
        out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        dp.send_msg(out)

    # =========================================================================
    # BAGIAN 3 — MONITOR KONGESTI (dari kode aslimu, sudah dibersihkan)
    # =========================================================================

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if dp.id not in self.datapaths:
                self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER:
            if dp.id in self.datapaths:
                self.logger.info("❌ Switch s%s disconnect", dp.id)
                del self.datapaths[dp.id]

    def _monitor(self):
        """Loop background: minta statistik port tiap MONITOR_INTERVAL detik"""
        while True:
            for dp in list(self.datapaths.values()):
                self._request_port_stats(dp)
            hub.sleep(MONITOR_INTERVAL)

    def _request_port_stats(self, dp):
        parser  = dp.ofproto_parser
        ofproto = dp.ofproto
        req = parser.OFPPortStatsRequest(dp, 0, ofproto.OFPP_ANY)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        dp_id = ev.msg.datapath.id
        for stat in ev.msg.body:
            port = stat.port_no
            if port != MONITOR_PORT:
                continue

            now  = stat.tx_bytes
            prev = self.prev_tx.get((dp_id, port), 0)

            # Handle counter reset (switch reboot)
            if now < prev:
                self.prev_tx[(dp_id, port)] = now
                continue

            delta = now - prev
            self.prev_tx[(dp_id, port)] = now

            mbps = (delta * 8) / (MONITOR_INTERVAL * 1_000_000)
            self.logger.info("📊 S%s P%s = %.2f Mbps", dp_id, port, mbps)

            # Deteksi kongesti
            key = (dp_id, port)
            if key not in self.prev_rate:
                self.prev_rate[key] = mbps
                continue

            prev_rate = self.prev_rate[key]
            if (prev_rate > 0 and
                    mbps > prev_rate * SPIKE_FACTOR and
                    mbps > MIN_SPIKE_MBPS):
                self.logger.warning(
                    "🚨 KONGESTI di S%s P%s (%.2f → %.2f Mbps)",
                    dp_id, port, prev_rate, mbps
                )
            self.prev_rate[key] = mbps

    # =========================================================================
    # HELPER
    # =========================================================================

    def _install_flow(self, dp, priority, match, actions,
                      idle_timeout=0, hard_timeout=0):
        ofproto = dp.ofproto
        parser  = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst,
            idle_timeout=idle_timeout, hard_timeout=hard_timeout
        )
        dp.send_msg(mod)
