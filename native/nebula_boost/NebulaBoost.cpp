#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>

#include "bakkesmod/plugin/bakkesmodplugin.h"
#include "bakkesmod/wrappers/includes.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>

#pragma comment(lib, "Ws2_32.lib")

namespace {
constexpr unsigned short kTelemetryPort = 29876;
constexpr auto kSampleInterval = std::chrono::milliseconds(50);
}

class NebulaBoostPlugin final : public BakkesMod::Plugin::BakkesModPlugin {
public:
    void onLoad() override;
    void onUnload() override;

private:
    void sampleAndSend();
    void sendSample(bool valid, float normalizedBoost);

    SOCKET socket_ = INVALID_SOCKET;
    sockaddr_in destination_{};
    std::uint32_t sequence_ = 0;
    std::chrono::steady_clock::time_point nextSample_{};
    bool winsockStarted_ = false;
};

BAKKESMOD_PLUGIN(
    NebulaBoostPlugin,
    "Nebula Boost Telemetry",
    "1.0.0",
    PLUGINTYPE_FREEPLAY | PLUGINTYPE_CUSTOM_TRAINING | PLUGINTYPE_REPLAY
)

void NebulaBoostPlugin::onLoad() {
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data) != 0) {
        return;
    }
    winsockStarted_ = true;
    socket_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (socket_ == INVALID_SOCKET) {
        WSACleanup();
        winsockStarted_ = false;
        return;
    }

    u_long nonBlocking = 1;
    ioctlsocket(socket_, FIONBIO, &nonBlocking);
    destination_.sin_family = AF_INET;
    destination_.sin_port = htons(kTelemetryPort);
    inet_pton(AF_INET, "127.0.0.1", &destination_.sin_addr);
    nextSample_ = std::chrono::steady_clock::now();

    gameWrapper->RegisterDrawable([this](CanvasWrapper) {
        sampleAndSend();
    });
}

void NebulaBoostPlugin::onUnload() {
    gameWrapper->UnregisterDrawables();
    if (socket_ != INVALID_SOCKET) {
        sendSample(false, 0.0F);
        closesocket(socket_);
        socket_ = INVALID_SOCKET;
    }
    if (winsockStarted_) {
        WSACleanup();
        winsockStarted_ = false;
    }
}

void NebulaBoostPlugin::sampleAndSend() {
    const auto now = std::chrono::steady_clock::now();
    if (now < nextSample_) {
        return;
    }
    nextSample_ = now + kSampleInterval;

    try {
        if (!gameWrapper->IsInGame()) {
            sendSample(false, 0.0F);
            return;
        }
        CarWrapper car = gameWrapper->GetLocalCar();
        if (car.IsNull()) {
            sendSample(false, 0.0F);
            return;
        }
        BoostWrapper boost = car.GetBoostComponent();
        if (boost.IsNull()) {
            sendSample(false, 0.0F);
            return;
        }
        const float current = boost.GetCurrentBoostAmount();
        const float maximum = boost.GetMaxBoostAmount();
        if (!std::isfinite(current) || !std::isfinite(maximum) || maximum <= 0.0F) {
            sendSample(false, 0.0F);
            return;
        }
        sendSample(true, std::clamp(current / maximum, 0.0F, 1.0F));
    } catch (...) {
        sendSample(false, 0.0F);
    }
}

void NebulaBoostPlugin::sendSample(bool valid, float normalizedBoost) {
    if (socket_ == INVALID_SOCKET) {
        return;
    }
    char payload[192]{};
    const int length = std::snprintf(
        payload,
        sizeof(payload),
        "{\"v\":2,\"seq\":%u,\"source\":\"rocket_league\",\"metric\":\"boost\",\"valid\":%s,\"value\":%.5f}",
        sequence_++,
        valid ? "true" : "false",
        valid ? normalizedBoost : 0.0F
    );
    if (length <= 0 || static_cast<std::size_t>(length) >= sizeof(payload)) {
        return;
    }
    sendto(
        socket_,
        payload,
        length,
        0,
        reinterpret_cast<const sockaddr*>(&destination_),
        sizeof(destination_)
    );
}
