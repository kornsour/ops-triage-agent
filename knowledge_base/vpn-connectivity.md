---
id: kb-vpn-connectivity
title: VPN disconnects and DNS resolution
owner: network-team
last_reviewed: 2026-03-22
tags: [vpn, network, dns, wifi]
---

# VPN disconnects and DNS resolution

Frequent VPN drops on home networks are usually caused by idle-timeout, an
overlapping local subnet, or DNS failing to fall back after reconnect.

1. Have the user switch the VPN profile from UDP to TCP, which survives flaky
   links better.
2. Set the client to use the corporate DNS resolvers explicitly rather than the
   ISP-assigned ones, which fixes the "DNS fails after reconnect" symptom.
3. If drops persist, collect the client logs and the home router model and
   escalate to the network team.

This is a **self-service** runbook: no guarded action is required unless the issue
must be escalated.
