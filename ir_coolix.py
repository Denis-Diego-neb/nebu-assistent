"""Temperatura Coolix em um quadro capturado, preservando modo e ventilacao.

Layout: IRremoteESP8266/src/ir_Coolix.h (TempMap e CoolixProtocol).
"""
import base64
import struct

TEMPS = (0, 1, 3, 2, 6, 7, 5, 4, 12, 13, 9, 8, 10, 11)


def decode(code):
    try:
        raw = base64.b64decode(code, validate=True)
        pulses = list(struct.unpack('<' + str(len(raw) // 2) + 'H', raw))
        if len(pulses) != 200:
            return None
        frames = []
        for offset in (0, 100):
            if not all(3500 < pulses[offset + i] < 5500 for i in (0, 1)):
                return None
            if not all(350 < pulses[offset+i] < 750 for i in range(2, 99, 2)):
                return None
            spaces = pulses[offset+3:offset+98:2]
            if not all(350 < s < 750 or 1250 < s < 2000 for s in spaces):
                return None
            bits = [int(s > 1000) for s in spaces]
            frame = [sum(bits[i+j] << (7-j) for j in range(8)) for i in range(0, 48, 8)]
            if any(frame[i] ^ frame[i+1] != 255 for i in (0, 2, 4)):
                return None
            frames.append(frame)
        if frames[0] != frames[1] or frames[0][0] != 0xB2:
            return None
        return pulses, frames[0]
    except (ValueError, TypeError, struct.error):
        return None


def temperature_code(code, temperature):
    if isinstance(temperature, bool) or not isinstance(temperature, int) or not 17 <= temperature <= 30:
        raise ValueError('A temperatura deste controle deve ficar entre 17 e 30 graus.')
    decoded = decode(code)
    if decoded is None:
        raise ValueError('O sinal aprendido nao corresponde a Coolix.')
    pulses, frame = decoded
    if (frame[4] & 15) != 0 or frame[4] >> 4 not in TEMPS:
        raise ValueError('Aprenda um sinal de ligar no modo frio para ajustar a temperatura.')
    frame[4] = (TEMPS[temperature-17] << 4) | (frame[4] & 15)
    frame[5] = frame[4] ^ 255
    for offset in (0, 100):
        for i, byte in enumerate(frame):
            for bit in range(8):
                pulses[offset+3+(i*8+bit)*2] = 1618 if byte & (1 << (7-bit)) else 536
    return base64.b64encode(struct.pack('<200H', *pulses)).decode('ascii')


def supports_temperature(code):
    try:
        temperature_code(code, 17)
        return True
    except ValueError:
        return False
