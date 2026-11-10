#pragma once
// Only the reviewed UDPv4 endpoint contract is implemented. Other transports
// remain unavailable. This helper reads metadata, never packet payloads.
#include <uxr/agent/transport/endpoint/IPv4EndPoint.hpp>
#include <uxr/agent/diagnostic/trace.hpp>
namespace tfg_xrce_trace {
template<typename Endpoint> inline PeerEndpoint packet_peer(const Endpoint&) noexcept { return {}; }
inline PeerEndpoint packet_peer(const eprosima::uxr::IPv4EndPoint& endpoint) noexcept {
    try {
        // Exact octet order used by the installed endpoint's public formatter;
        // get_port() is its displayed host-order port. No guessed network swaps.
        const auto a=endpoint.get_addr();
        PeerEndpoint out;
        out.address=std::to_string(a & 255)+"."+std::to_string((a>>8)&255)+"."+
                    std::to_string((a>>16)&255)+"."+std::to_string((a>>24)&255);
        out.port=endpoint.get_port(); out.available=out.port>0 && a!=0; return out;
    } catch (...) { return {}; }
}
template<typename Endpoint>
inline MessagePeer received_peer(unsigned long long, unsigned, unsigned, const Endpoint&) noexcept { return {}; }
inline MessagePeer received_peer(unsigned long long instance, unsigned key, unsigned session,
                                 const eprosima::uxr::IPv4EndPoint& endpoint) noexcept {
    MessagePeer out; out.instance=instance; out.key=key; out.session=session;
    out.address=endpoint.get_addr(); out.port=endpoint.get_port();
    out.available=out.address!=0 && out.port>0; return out;
}
inline PeerEndpoint peer_from_message(const MessagePeer& metadata, unsigned long long instance,
                                      unsigned key, unsigned session) noexcept {
    if (!metadata.available || metadata.instance!=instance || metadata.key!=key || metadata.session!=session)
        return {};
    return packet_peer(eprosima::uxr::IPv4EndPoint(metadata.address,metadata.port));
}
}
