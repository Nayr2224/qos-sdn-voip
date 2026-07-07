#!/usr/bin/env python3

from mininet.topo import Topo
from mininet.link import TCLink


class QosTopo(Topo):
    def build(self):
        # Switch
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')

        # Host
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')
        h3 = self.addHost('h3', ip='10.0.0.3/24')
        h4 = self.addHost('h4', ip='10.0.0.4/24')
        h5 = self.addHost('h5', ip='10.0.0.5/24')
        h6 = self.addHost('h6', ip='10.0.0.6/24')

        # Bottleneck link (inti QoS test)
        self.addLink(s1, s2, cls=TCLink, bw=10, delay='5ms')
        self.addLink(s1, s3, cls=TCLink, bw=10, delay='5ms')

        # Access link
        self.addLink(s2, h1, cls=TCLink, bw=100, delay='1ms')
        self.addLink(s2, h2, cls=TCLink, bw=100, delay='1ms')
        self.addLink(s2, h3, cls=TCLink, bw=100, delay='1ms')

        self.addLink(s3, h4, cls=TCLink, bw=100, delay='1ms')
        self.addLink(s3, h5, cls=TCLink, bw=100, delay='1ms')
        self.addLink(s3, h6, cls=TCLink, bw=100, delay='1ms')


topos = {'qostopo': (lambda: QosTopo())}
